"""
fallback/lambda_handler.py
──────────────────────────
Fallback Trend Lambda — acionada pelo Step Functions quando o Agno retorna
trend_score < 0.6 (CheckTrendScore → UseFallbackTrend).

Estratégia em duas camadas:
  1. Consulta DynamoDB (pulsocast-trend-cache) pelo item com maior trend_score
     persistido nas últimas 7 dias para o mesmo niche.
  2. Se nada encontrado, retorna um TrendPayload padrão seguro para MT Hospitalar.

Entry-point: lambda_handler(event, context) → dict
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key, Attr

from schemas import (
    ContentPillar,
    ContentStrategyRecommendation,
    HookOption,
    HospitalSector,
    PlatformSignal,
    Platform,
    PostFormat,
    PostTone,
    Sentiment,
    TrendCategory,
    TrendPayload,
)

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

_TABLE_NAME = os.getenv("TREND_CACHE_TABLE", "pulsocast-trend-cache")
_DYNAMODB    = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))


# ─── Lambda entry-point ───────────────────────────────────────────────────────

def lambda_handler(event: dict, context: Any) -> dict:
    """
    Event: { "niche": str, "reason": str }
    Returns: { "status": "ok|fallback", "trend_payload": dict }
    """
    niche  = event.get("niche",  "musicoterapia hospitalar")
    reason = event.get("reason", "trend_score_below_threshold")

    logger.info(f"Fallback triggered | niche='{niche}' reason='{reason}'")

    payload = _query_cache(niche) or _default_payload(niche)

    logger.info(
        f"Fallback payload | topic='{payload.consolidated_topic}' "
        f"score={payload.trend_score:.2f}"
    )
    return {
        "status":        "fallback",
        "trend_payload": payload.model_dump(mode="json"),
    }


# ─── DynamoDB cache lookup ────────────────────────────────────────────────────

def _query_cache(niche: str) -> TrendPayload | None:
    """Busca o trend com maior score nos últimos 7 dias para o niche."""
    try:
        table     = _DYNAMODB.Table(_TABLE_NAME)
        cutoff    = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        response  = table.query(
            KeyConditionExpression=Key("niche").eq(niche),
            FilterExpression=Attr("captured_at").gte(cutoff),
            ScanIndexForward=False,   # mais recente primeiro
            Limit=10,
        )
        items = response.get("Items", [])
        if not items:
            return None

        best = max(items, key=lambda x: float(x.get("trend_score", 0)))
        payload = TrendPayload.model_validate(best["trend_payload"])
        logger.info(f"Cache hit | topic='{payload.consolidated_topic}' score={payload.trend_score:.2f}")
        return payload

    except Exception as exc:
        logger.warning(f"DynamoDB cache lookup failed: {exc} — using default payload")
        return None


# ─── Default payload ──────────────────────────────────────────────────────────

def _default_payload(niche: str) -> TrendPayload:
    """
    TrendPayload padrão seguro para MT Hospitalar.
    Usado quando não há cache disponível e o Agno ficou abaixo do threshold.
    Score fixo em 0.62 (acima do gate de 0.6) para permitir a continuação do pipeline.
    """
    return TrendPayload(
        trend_id=str(uuid.uuid4()),
        captured_at=datetime.utcnow(),
        consolidated_topic=(
            "Musicoterapia como recurso de humanização hospitalar: "
            "evidências e prática clínica"
        ),
        topic_keywords=[
            "musicoterapia", "humanização hospitalar", "evidência clínica",
            "bem-estar do paciente", "equipe multiprofissional",
        ],
        trend_score=0.62,
        trend_category=TrendCategory.HUMANIZATION,
        target_audience=(
            "Profissionais de saúde, gestores de humanização hospitalar e "
            "familiares de pacientes internados"
        ),
        context_summary=(
            "A humanização hospitalar segue como tema perene de engajamento em saúde. "
            "Conteúdos educativos sobre o papel da musicoterapia no contexto clínico "
            "têm desempenho consistente em plataformas de saúde. "
            "Este é um ângulo seguro e ético para publicação."
        ),
        platform_signals=[
            PlatformSignal(
                platform=Platform.INSTAGRAM,
                topic="musicoterapia hospitalar",
                volume_score=0.55,
                growth_rate=5.0,
                sentiment=Sentiment.POSITIVE,
                top_hashtags=[
                    "#musicoterapia", "#musicoterapiahospitalar",
                    "#humanizacaohospitalar", "#saudecompleta",
                    "#musicoterapeuta",
                ],
                sample_content=[],
                influencer_signals=[],
            )
        ],
        similar_historical_trend_ids=[],
        content_strategy=ContentStrategyRecommendation(
            content_pillar=ContentPillar.EDUCACAO,
            hospital_sector=HospitalSector.GERAL,
            recommended_format=PostFormat.FEED,
            recommended_tone=PostTone.EDUCATIONAL,
            narrative_angle=(
                "Desmistificar o que a musicoterapia faz (e não faz) no hospital — "
                "diferenciando prática clínica de 'música ambiente'"
            ),
            hook_options=[
                HookOption(
                    text="Musicoterapia não é colocar uma playlist. Entenda o que muda quando um musicoterapeuta entra na UTI.",
                    rationale="Corrige equívoco comum; gera curiosidade em profissionais de saúde",
                ),
                HookOption(
                    text="3 objetivos clínicos que só a musicoterapia estruturada consegue alcançar no ambiente hospitalar.",
                    rationale="Dado de lista com número; posiciona autoridade técnica",
                ),
            ],
            scientific_anchors=[],
            emerging_terms=["humanização hospitalar", "equipe multiprofissional", "prática baseada em evidências"],
            trending_hashtags=[
                "#musicoterapia", "#musicoterapiahospitalar",
                "#humanizacaohospitalar", "#saudecompleta",
            ],
            ethical_risks=[],
            requires_tcle=False,
            show_epi=False,
            strategy_rationale=(
                "Conteúdo educativo sobre a diferença entre musicoterapia clínica e música ambiente "
                "é evergreen, seguro eticamente, e tem alta relevância para o público-alvo. "
                "Usado como fallback quando nenhuma tendência ativa superou o threshold de 0.6."
            ),
        ),
    )
