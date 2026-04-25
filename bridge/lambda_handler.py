"""
bridge/lambda_bridge_v2.py
──────────────────────────
Lambda Bridge v2 — Musicoterapia Hospitalar.

MUDANÇA PRINCIPAL em relação à v1:
  v1: Bridge carregava brand_context do SSM e usava para definir estratégia
  v2: Bridge só carrega BrandIdentity do SSM (voz, ética, linguagem proibida)
      A estratégia de conteúdo (pilar, setor, ângulo, gancho) vem do TrendPayload.content_strategy

RESPONSABILIDADE DA BRIDGE v2:
  1. Validar TrendPayload (schema + threshold de score)
  2. Carregar BrandIdentity do SSM (apenas identidade imutável)
  3. Sanitizar strings do content_strategy (prompt injection prevention)
  4. Resolver formato do post (explicit > content_strategy.recommended_format > default)
  5. Agregar hashtags de plataforma + trending_hashtags do content_strategy
  6. Montar ContextBrief com separação explícita brand_identity / trend_context / content_strategy
  7. Passar guardrails éticos contextuais do content_strategy para o ContextBrief

Entry-point: handler(event, context) → dict
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from typing import Any

import boto3
from pydantic import ValidationError

from schemas_v2 import (
    BrandIdentity,
    ContextBrief,
    ContentStrategyRecommendation,
    PlatformInsights,
    PostFormat,
    PostRequirements,
    TrendContext,
    TrendPayload,
)

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))

_brand_cache: dict[str, BrandIdentity] = {}

_INJECTION_PATTERN = re.compile(
    r"(</s>|<\|im_end\|>|###\s*system|###\s*user|\[INST\]|\[\/INST\]|<\|endoftext\|>)",
    re.IGNORECASE,
)


# ─── Entry-point ──────────────────────────────────────────────────────────────

def handler(event: dict, context: Any) -> dict:
    """
    Lambda Bridge v2.

    Event:
    {
        "trend_payload":  { ...TrendPayload com content_strategy... },
        "brand_id":       "musicoterapia-hospitalar",
        "post_format":    "feed" | null,   // override explícito
        "language":       "pt-BR"
    }

    Returns:
    {
        "status":         "ok",
        "context_brief":  { ...ContextBrief... },
        "brief_id":       "uuid",
        "trend_id":       "uuid",
        "pilar":          "ciencia",
        "setor":          "uti",
        "requires_tcle":  false
    }
    """
    logger.info("Bridge v2 invoked", extra={"keys": list(event.keys())})

    try:
        # ── 1. Validar TrendPayload ────────────────────────────────────────
        raw_payload = event.get("trend_payload")
        if not raw_payload:
            raise ValueError("Missing 'trend_payload' in event")

        trend_payload = TrendPayload.model_validate(raw_payload)
        strategy      = trend_payload.content_strategy

        logger.info(
            f"TrendPayload OK | topic='{trend_payload.consolidated_topic}' "
            f"score={trend_payload.trend_score:.2f} "
            f"pilar={strategy.content_pillar.value} "
            f"setor={strategy.hospital_sector.value}"
        )

        # ── 2. Carregar apenas BrandIdentity do SSM ───────────────────────
        brand_id       = event.get("brand_id", "musicoterapia-hospitalar")
        brand_identity = _load_brand_identity(brand_id)

        # ── 3. Resolver formato ───────────────────────────────────────────
        post_format = _resolve_post_format(
            explicit=event.get("post_format"),
            strategy_recommended=strategy.recommended_format,
        )

        # ── 4. Sanitizar campos do content_strategy ───────────────────────
        sanitized_strategy = _sanitize_strategy(strategy)

        # ── 5. Agregar hashtags ───────────────────────────────────────────
        platform_hashtags = _aggregate_hashtags(trend_payload)
        all_hashtags = list(dict.fromkeys(
            sanitized_strategy.trending_hashtags + platform_hashtags
        ))[:30]

        # ── 6. Montar ContextBrief ────────────────────────────────────────
        language = event.get("language", "pt-BR")
        context_brief = _build_context_brief(
            trend_payload=trend_payload,
            brand_identity=brand_identity,
            sanitized_strategy=sanitized_strategy,
            all_hashtags=all_hashtags,
            post_format=post_format,
            language=language,
        )

        logger.info(
            f"ContextBrief built | brief_id={context_brief.brief_id} "
            f"requires_tcle={strategy.requires_tcle} "
            f"show_epi={strategy.show_epi}"
        )

        return {
            "status":        "ok",
            "context_brief": context_brief.model_dump(mode="json"),
            "brief_id":      context_brief.brief_id,
            "trend_id":      context_brief.trend_id,
            # Metadados úteis para Step Functions gates downstream
            "pilar":         strategy.content_pillar.value,
            "setor":         strategy.hospital_sector.value,
            "requires_tcle": strategy.requires_tcle,
            "show_epi":      strategy.show_epi,
        }

    except ValidationError as exc:
        logger.error(f"Schema validation failed: {exc.json()}")
        return {"status": "error", "error_type": "validation", "detail": exc.errors()}
    except Exception as exc:
        logger.exception("Unhandled error in Bridge v2")
        return {"status": "error", "error_type": "internal", "detail": str(exc)}


# ─── Core transformation ──────────────────────────────────────────────────────

def _build_context_brief(
    trend_payload: TrendPayload,
    brand_identity: BrandIdentity,
    sanitized_strategy: ContentStrategyRecommendation,
    all_hashtags: list[str],
    post_format: PostFormat,
    language: str,
) -> ContextBrief:
    """
    Monta o ContextBrief mesclando:
      - BrandIdentity (SSM — imutável)
      - TrendPayload (Agno — sinais brutos)
      - ContentStrategyRecommendation (Agno — estratégia dinâmica)
    """
    platform_names = {s.platform.value for s in trend_payload.platform_signals}
    best_formats   = _infer_best_formats(platform_names, post_format)
    benchmarks     = _compute_benchmarks(trend_payload)

    platform_insights = PlatformInsights(
        top_hashtags=all_hashtags,
        best_formats=best_formats,
        engagement_benchmarks=benchmarks,
    )

    trend_context = TrendContext(
        topic=_sanitize(trend_payload.consolidated_topic),
        keywords=[_sanitize(kw) for kw in trend_payload.topic_keywords],
        trend_score=trend_payload.trend_score,
        category=trend_payload.trend_category,
        context_summary=_sanitize(trend_payload.context_summary),
        platform_insights=platform_insights,
        target_audience=_sanitize(trend_payload.target_audience),
    )

    post_requirements = PostRequirements(
        format=post_format,
        language=language,
    )

    return ContextBrief(
        trend_id=trend_payload.trend_id,
        brand_identity=brand_identity,
        trend_context=trend_context,
        content_strategy=sanitized_strategy,
        post_requirements=post_requirements,
    )


# ─── BrandIdentity loading ────────────────────────────────────────────────────

def _load_brand_identity(brand_id: str) -> BrandIdentity:
    """
    Carrega BrandIdentity do SSM.

    Diferença da v1: o SSM agora só contém identidade imutável.
    Pilares, setores e estratégia de conteúdo NÃO estão mais aqui.

    SSM path: /trendcast/brand/{brand_id}/identity
    """
    cache_key = f"brand_identity:{brand_id}"
    if cache_key in _brand_cache:
        return _brand_cache[cache_key]

    param_path = f"/trendcast/brand/{brand_id}/identity"
    try:
        response    = ssm.get_parameter(Name=param_path, WithDecryption=False)
        raw         = json.loads(response["Parameter"]["Value"])
        brand_id_   = BrandIdentity.model_validate(raw)
        _brand_cache[cache_key] = brand_id_
        logger.info(f"BrandIdentity loaded | brand={brand_id}")
        return brand_id_

    except ssm.exceptions.ParameterNotFound:
        logger.warning(f"SSM '{param_path}' not found — using default")
        return _default_brand_identity()
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.error(f"Invalid BrandIdentity in SSM: {exc}")
        return _default_brand_identity()


def _default_brand_identity() -> BrandIdentity:
    return BrandIdentity(
        brand_name="Musicoterapia Hospitalar",
        professional_id="Mt. [Nome] — Musicoterapeuta",
        brand_voice=(
            "Profissional de saúde na linha de frente. "
            "Tom humano, científico e esperançoso. "
            "Educa sem simplificar. Inspira sem prometer curas."
        ),
        brand_values=["evidência científica", "dignidade do paciente", "humanização hospitalar"],
        target_audience=(
            "Profissionais de saúde, familiares de pacientes hospitalizados, "
            "público geral curioso sobre saúde integrativa."
        ),
        ethical_frameworks=[
            "Código Nacional de Ética UBAM (2018)",
            "Diretrizes Éticas ABMT (2025)",
            "Lei Federal 14.842/2024",
            "LGPD — Lei nº 13.709/2018",
        ],
        forbidden_language=[
            "cura", "música cura", "curou", "cura pela música",
            "garante", "100% eficaz", "sempre funciona",
            "tratamento definitivo", "elimina a doença",
        ],
        required_disclaimers={
            "case_report": (
                "[Relato anonimizado. Autorização obtida. "
                "Dados identificadores suprimidos — UBAM Art. 52.]"
            ),
            "tcle": (
                "[Conteúdo publicado com Termo de Consentimento Livre e Esclarecido assinado.]"
            ),
        },
        clinical_context=(
            "Musicoterapeuta hospitalar atuando em contexto multiprofissional. "
            "Prática baseada em evidências com objetivos clínicos definidos em prontuário."
        ),
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_post_format(
    explicit: str | None,
    strategy_recommended: PostFormat,
) -> PostFormat:
    """
    Prioridade: override explícito > recomendação do Agno (content_strategy).
    Na v2, o Agno já faz a inferência — não precisamos mais de heurísticas locais.
    """
    if explicit:
        try:
            return PostFormat(explicit)
        except ValueError:
            logger.warning(f"Unknown post_format '{explicit}' — using Agno recommendation")
    return strategy_recommended


def _sanitize_strategy(
    strategy: ContentStrategyRecommendation,
) -> ContentStrategyRecommendation:
    """Sanitiza campos de texto do content_strategy contra prompt injection."""
    return strategy.model_copy(update={
        "narrative_angle":    _sanitize(strategy.narrative_angle),
        "strategy_rationale": _sanitize(strategy.strategy_rationale),
        "hook_options": [
            h.model_copy(update={"text": _sanitize(h.text)})
            for h in strategy.hook_options
        ],
        "scientific_anchors": [
            a.model_copy(update={
                "claim":       _sanitize(a.claim),
                "source_hint": _sanitize(a.source_hint),
            })
            for a in strategy.scientific_anchors
        ],
        "emerging_terms":    [_sanitize(t) for t in strategy.emerging_terms],
        "ethical_risks":     [_sanitize(r) for r in strategy.ethical_risks],
    })


def _aggregate_hashtags(payload: TrendPayload) -> list[str]:
    all_hashtags: list[str] = []
    for signal in payload.platform_signals:
        all_hashtags.extend(signal.top_hashtags)
    return [tag for tag, _ in Counter(all_hashtags).most_common(20)]


def _infer_best_formats(platform_names: set[str], primary: PostFormat) -> list[PostFormat]:
    formats: list[PostFormat] = [primary]
    if ("tiktok" in platform_names or "youtube" in platform_names) \
            and PostFormat.REEL not in formats:
        formats.append(PostFormat.REEL)
    if "instagram" in platform_names and PostFormat.STORY not in formats:
        formats.append(PostFormat.STORY)
    return formats


def _compute_benchmarks(payload: TrendPayload) -> dict[str, int]:
    all_reaches = [
        sig.reach
        for ps in payload.platform_signals
        for sig in ps.influencer_signals
        if sig.reach > 0
    ]
    avg_reach = sum(all_reaches) / len(all_reaches) if all_reaches else 8_000
    er = 0.035
    return {
        "avg_likes":    int(avg_reach * er * 0.80),
        "avg_comments": int(avg_reach * er * 0.15),
        "avg_shares":   int(avg_reach * er * 0.05),
    }


def _sanitize(text: str) -> str:
    cleaned = _INJECTION_PATTERN.sub("", text)
    if cleaned != text:
        logger.warning("Prompt injection tokens removed from Agno output")
    return cleaned.strip()
