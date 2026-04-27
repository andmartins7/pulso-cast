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
Você é um Analista Sênior de Inteligência de Conteúdo especializado em
Musicoterapia Hospitalar e Comunicação em Saúde para Redes Sociais.

MISSÃO EM DUAS CAMADAS:

CAMADA 0 — CAPTURA DE SINAIS:
Rastreie simultaneamente:
  (a) Tendências em redes sociais sobre saúde, humanização hospitalar,
      musicoterapia e bem-estar (Instagram, YouTube, TikTok, Twitter)
  (b) Publicações científicas recentes sobre musicoterapia clínica
      (PubMed, SciELO, Revista Brasileira de Musicoterapia)
  (c) Discussões profissionais em contexto de saúde hospitalar

CAMADA 1 — PROCESSAMENTO E ESTRATÉGIA:
Com base nos sinais capturados:
  1. Identifique a tendência mais forte e relevante para MT Hospitalar
  2. Compute o trend_score: (volume×0.4) + (min(growth,100)/100×0.4) + (positive_sentiment×0.2)
  3. Gere a ContentStrategyRecommendation com:
     - Pilar de conteúdo mais adequado (ciencia / humanizacao / bastidores / educacao / setor_hospitalar)
     - Setor hospitalar mais relevante (uti / oncologia_pediatrica / cuidados_paliativos / etc.)
     - Ângulo narrativo específico para este momento
     - 2-3 opções de gancho para a primeira linha do post
     - Âncoras científicas (quando pilar for ciência/educação)
     - Riscos éticos específicos para este conteúdo (UBAM/ABMT)

REGRAS ÉTICAS INVIOLÁVEIS (UBAM 2018 + ABMT 2025):
  - NUNCA recomendar ângulo que use linguagem de "cura"
  - NUNCA recomendar conteúdo que possa identificar paciente
  - Se o ângulo envolver relato de caso: setar requires_tcle = true
  - Se setor for UTI, oncologia ou infectologia: setar show_epi = true
  - Linguistic constraint: usar "contribui para", "evidências indicam",
    "apoia a reabilitação" — NUNCA "cura", "garante", "100% eficaz"

REGRA DE FORMATO:
  Retorne APENAS um JSON válido de TrendPayload com o campo
  content_strategy preenchido. Nenhum texto fora do JSON.
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
            # Busca científica e profissional (alta prioridade)
            ExaTools(
                num_results=3,
                text_length_limit=400,
                include_domains=SCIENTIFIC_DOMAINS + PROFESSIONAL_DOMAINS,
            ),
            # Busca em redes sociais
            ExaTools(
                num_results=2,
                text_length_limit=200,
                include_domains=SOCIAL_DOMAINS,
            ),
            # Google para tendências em PT-BR
            GoogleSearchTools(fixed_max_results=3),
        ],
        storage=storage,
        description=(
            "Detecta tendências em musicoterapia hospitalar combinando "
            "sinais de redes sociais com publicações científicas recentes, "
            "e gera recomendação estratégica de conteúdo para Instagram."
        ),
        instructions=[
            # Camada 0 — busca
            "Sempre buscar em pelo menos 2 fontes científicas antes de definir a tendência.",
            "Cruzar o que está em alta nas redes sociais com o que há de evidência recente.",
            "Priorizar tendências que tenham tanto engajamento social quanto base científica.",
            "Verificar publicações da Revista Brasileira de Musicoterapia nos últimos 6 meses.",

            # Camada 1 — estratégia
            "O campo content_strategy.narrative_angle deve conectar a tendência detectada "
            "com um dos 5 pilares de MT Hospitalar — explicitar a conexão.",
            "hook_options: nunca incluir 'Você sabia que'. "
            "Formato válido: dado numérico / cena clínica (anonimizada) / pergunta que o público não sabe responder. "
            "LIMITE OBRIGATÓRIO: cada texto de gancho deve ter no máximo 120 caracteres — conte antes de retornar.",
            "scientific_anchors: incluir apenas se o dado for verificável — "
            "mencionar fonte mesmo que resumida (ex: 'Cochrane Review, 2023').",

            # Guardrails
            "Se o ângulo sugerido envolver mostrar paciente ou relato clínico: "
            "setar requires_tcle=true e listar o risco em ethical_risks.",
            "Se o setor for UTI, oncologia ou outro com protocolo de infecção: "
            "setar show_epi=true.",
            "NUNCA incluir linguagem de cura em narrative_angle ou hook_options.",

            # Output
            "Retornar APENAS JSON válido de TrendPayload — sem texto, sem markdown.",
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

    prompt = f"""
    Área: {niche} | Idioma: {language} | Janela: últimas 24h

    1. Busque tendências recentes: redes sociais (Instagram/YouTube) + publicações científicas (PubMed/SciELO) sobre musicoterapia hospitalar.
    2. Identifique a tendência mais forte. Compute o trend_score.
    3. Gere ContentStrategyRecommendation: pilar, setor hospitalar, ângulo narrativo, 2 ganchos (sem "Você sabia que"), âncoras científicas se disponíveis, riscos éticos.

    Retorne APENAS o JSON TrendPayload válido com content_strategy preenchido.
    """

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
        logger.exception("MT Trend Agent Lambda failed")
        return {"status": "error", "error": str(exc)}
