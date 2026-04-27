"""
agno_agent/trend_agent_musicoterapia.py
───────────────────────────────────────
Agno Trend Agent especializado para Musicoterapia Hospitalar.

DIFERENÇA PRINCIPAL em relação ao trend_agent.py genérico:
  - Camada 0: busca em fontes científicas + redes sociais de saúde
  - Camada 1: além de detectar tendências, gera ContentStrategyRecommendation
    (pilar, setor, ângulo, gancho, âncoras científicas, riscos éticos)

O agent agora entrega TrendPayload COM content_strategy embutido.
A Lambda Bridge apenas valida e formata — não mais decide a estratégia.

Entry-point: run_trend_analysis(niche, language) → TrendPayload
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.storage.agent.dynamodb import DynamoDbAgentStorage
from agno.tools.exa import ExaTools
from agno.tools.googlesearch import GoogleSearchTools

from schemas import (
    TrendPayload,
)

logger = logging.getLogger(__name__)


# ─── Camada 0 — Fontes de busca ───────────────────────────────────────────────

SCIENTIFIC_DOMAINS = [
    "pubmed.ncbi.nlm.nih.gov",
    "scielo.br",
    "musicoterapia.revistademusicoterapia.mus.br",  # Revista Brasileira de MT
    "wfmt.info",
    "journals.lww.com",
    "nature.com",
    "thelancet.com",
]

SOCIAL_DOMAINS = [
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
]

PROFESSIONAL_DOMAINS = [
    "ubammusicoterapia.com.br",
    "abmtmusicoterapia.com.br",
    "cfm.org.br",             # Conselho Federal de Medicina
    "cofen.gov.br",           # Conselho Federal de Enfermagem
    "hospitalar.com.br",
    "einstein.br",
    "hsl.org.br",
]


# ─── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
Analista de tendências para Musicoterapia Hospitalar (MT).
Busque sinais em redes sociais + publicações científicas e retorne um TrendPayload JSON.

ÉTICA (UBAM 2018 + ABMT 2025): nunca linguagem de "cura"; requires_tcle=true se relato clínico; show_epi=true se UTI/oncologia/infectologia.
FORMATO: APENAS JSON TrendPayload válido, sem texto extra.
"""


# ─── Agno Agent factory ───────────────────────────────────────────────────────

def build_mt_trend_agent(
    model_id: str = "claude-sonnet-4-20250514",
    storage_table: str = "trendcast-mt-agent-sessions",
    use_dynamodb_storage: bool = True,
) -> Agent:
    """
    Constrói o Agno Trend Agent especializado para Musicoterapia Hospitalar.

    Fontes de busca (Camada 0):
      - ExaTools com domínios científicos + sociais + profissionais
      - GoogleSearchTools para tendências em PT-BR
    """
    storage = None
    if use_dynamodb_storage:
        storage = DynamoDbAgentStorage(
            table_name=storage_table,
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )

    return Agent(
        name="MusicoterapiaHospitalarTrendAgent",
        model=Claude(id=model_id),
        tools=[
            # Busca científica — resultados mínimos para controlar tokens
            ExaTools(
                num_results=2,
                text_length_limit=200,
                include_domains=SCIENTIFIC_DOMAINS + PROFESSIONAL_DOMAINS,
            ),
            # Google para tendências em PT-BR
            GoogleSearchTools(fixed_max_results=2),
        ],
        storage=storage,
        description="Detecta tendências em MT Hospitalar e gera ContentStrategy para Instagram.",
        instructions=[
            "Faça 1 busca científica (PubMed/SciELO) e 1 busca Google sobre MT hospitalar.",
            "Identifique a tendência mais forte. Compute trend_score = (volume×0.4)+(growth/100×0.4)+(sentiment×0.2).",
            "hook_options: 2 ganchos, máximo 120 caracteres cada, sem 'Você sabia que'.",
            "NUNCA usar linguagem de cura. Apenas JSON TrendPayload — sem texto extra.",
        ],
        response_model=TrendPayload,
        structured_outputs=True,
        markdown=False,
        show_tool_calls=True,
    )


# ─── Entry-point ──────────────────────────────────────────────────────────────

def run_trend_analysis(
    niche: str = "musicoterapia hospitalar",
    language: str = "pt-BR",
    agent: Optional[Agent] = None,
) -> TrendPayload:
    """
    Executa análise de tendência especializada para MT Hospitalar.

    Retorna TrendPayload com content_strategy preenchido pelo Agno.
    O campo content_strategy substitui a lógica de estratégia que antes
    ficava no brand_context estático do SSM.
    """
    if agent is None:
        agent = build_mt_trend_agent()

    prompt = (
        f"Área: {niche} | Idioma: {language} | Janela: últimas 24h. "
        "Busque 1 fonte científica + 1 Google. Identifique tendência, compute trend_score, "
        "gere ContentStrategyRecommendation com 2 ganchos (≤120 chars cada). "
        "Retorne APENAS JSON TrendPayload."
    )

    logger.info(f"Agno MT analysis | niche='{niche}' lang='{language}'")
    response = agent.run(prompt)

    if isinstance(response.content, TrendPayload):
        payload = response.content
    else:
        raw = response.content
        if isinstance(raw, list):
            raw = " ".join(
                part.text if hasattr(part, "text") else str(part) for part in raw
            )
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        payload = TrendPayload.model_validate_json(clean)

    # Truncate hook texts that exceed the 120-char Pydantic limit
    for hook in payload.content_strategy.hook_options:
        if len(hook.text) > 120:
            cut = hook.text[:120].rsplit(" ", 1)[0]
            logger.warning(f"Hook truncated: {hook.text!r} → {cut!r}")
            hook.text = cut

    logger.info(
        f"TrendPayload OK | topic='{payload.consolidated_topic}' "
        f"score={payload.trend_score:.2f} "
        f"pilar={payload.content_strategy.content_pillar.value} "
        f"setor={payload.content_strategy.hospital_sector.value}"
    )
    return payload


# ─── Lambda handler ───────────────────────────────────────────────────────────

def lambda_handler(event: dict, context) -> dict:
    """
    Entry-point Lambda.

    Event: { "niche": str, "language": str }
    Returns: { "status": "ok", "trend_payload": dict }
    """
    niche    = event.get("niche",    "musicoterapia hospitalar")
    language = event.get("language", "pt-BR")

    try:
        payload = run_trend_analysis(niche=niche, language=language)
        return {
            "status":        "ok",
            "trend_payload": payload.model_dump(mode="json"),
            "pilar":         payload.content_strategy.content_pillar.value,
            "setor":         payload.content_strategy.hospital_sector.value,
        }
    except Exception as exc:
        err_str = str(exc)
        # Re-raise rate limit errors so Step Functions can retry with backoff
        if "rate_limit" in err_str or "429" in err_str or "rate limit" in err_str.lower():
            logger.warning("Anthropic rate limit hit — propagating for Step Functions retry")
            raise
        logger.exception("MT Trend Agent Lambda failed")
        return {"status": "error", "error": err_str}
