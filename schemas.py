"""
schemas_v2.py — Contratos Pydantic v2 para o TrendCast (revisão arquitetural).

MUDANÇA PRINCIPAL em relação à v1:
─────────────────────────────────
Separação de responsabilidades no contrato de dados:

  ANTES:  BrandContext (SSM) continha TUDO — identidade + estratégia de conteúdo
  AGORA:  BrandIdentity (SSM, estático) + ContentStrategyRecommendation (Agno, dinâmico)

  BrandIdentity               Agno TrendAgent
  (SSM — imutável)            (Camadas 0+1 — tempo real)
        │                              │
        └──────────┬───────────────────┘
                   ▼
           Lambda Bridge
                   │
                   ▼
            ContextBrief  →  CrewAI

Responsabilidade de cada parte:
  BrandIdentity        : VOZ, VALORES, ÉTICA, LINGUAGEM PROIBIDA
  ContentStrategy      : PILAR DO DIA, SETOR, ÂNGULO, GANCHO, DADOS CIENTÍFICOS
  TrendPayload         : SINAIS DE PLATAFORMA, SCORE, KEYWORDS, SENTIMENTO
  ContextBrief         : merge dos três → input completo para o CrewAI
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────────────

class Platform(str, Enum):
    INSTAGRAM      = "instagram"
    YOUTUBE        = "youtube"
    TIKTOK         = "tiktok"
    TWITTER        = "twitter"
    GOOGLE_TRENDS  = "google_trends"
    PUBMED         = "pubmed"          # novo: busca científica relevante p/ MT
    SCIELO         = "scielo"          # novo: produção acadêmica brasileira


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL  = "neutral"
    NEGATIVE = "negative"


class TrendCategory(str, Enum):
    HEALTH         = "health"
    EDUCATION      = "education"
    SCIENCE        = "science"
    HUMANIZATION   = "humanization"
    REHABILITATION = "rehabilitation"
    MENTAL_HEALTH  = "mental_health"
    PALLIATIVE     = "palliative_care"
    TECHNOLOGY     = "technology"
    OTHER          = "other"


class PostFormat(str, Enum):
    FEED      = "feed"
    STORY     = "story"
    REEL      = "reel"
    CAROUSEL  = "carousel"


class PostTone(str, Enum):
    SCIENTIFIC    = "scientific"     # dados, evidências, mecanismos
    HUMANIZED     = "humanized"      # história, vínculo, impacto emocional
    EDUCATIONAL   = "educational"    # desmistificação, mito x verdade
    BACKSTAGE     = "backstage"      # bastidores, rotina profissional
    EMPATHETIC    = "empathetic"     # cuidados paliativos, fim de vida
    AUTHORITATIVE = "authoritative"  # posicionamento profissional/legislação


# ─── Enums específicos para Musicoterapia Hospitalar ─────────────────────────

class ContentPillar(str, Enum):
    """Os 5 pilares de conteúdo para MT Hospitalar — gerados pelo Agno."""
    CIENCIA         = "ciencia"          # neurociência, evidências, biomarcadores
    HUMANIZACAO     = "humanizacao"      # relato humano, vínculo, impacto
    BASTIDORES      = "bastidores"       # rotina profissional, instrumentos, EPI
    EDUCACAO        = "educacao"         # desmistificação, mito x verdade
    SETOR_HOSPITALAR = "setor_hospitalar" # UTI, Oncologia, Paliativo, etc.


class HospitalSector(str, Enum):
    """Setores hospitalares onde a MT atua — gerado pelo Agno com base nos sinais."""
    UTI             = "uti"
    ONCOLOGIA_PED   = "oncologia_pediatrica"
    PALIATIVO       = "cuidados_paliativos"
    NEONATAL        = "uti_neonatal"
    REABILITACAO    = "reabilitacao_neurologica"
    SAUDE_MENTAL    = "saude_mental_psiquiatria"
    MATERNIDADE     = "maternidade"
    GERAL           = "geral"


# ─── ContentStrategyRecommendation (NOVO — gerado pelo Agno) ─────────────────

class ScientificAnchor(BaseModel):
    """Dado ou estudo científico identificado pelo Agno para ancorar o post."""
    claim:        str  = Field(description="Afirmação científica em linguagem acessível")
    source_hint:  str  = Field(description="Referência resumida: autor, ano ou journal")
    quantified:   bool = Field(default=False,
        description="True se o dado é numérico (ex: 'reduz cortisol em 12%')")


class HookOption(BaseModel):
    """Uma opção de gancho para a primeira linha do caption."""
    text:     str  = Field(max_length=120, description="Gancho em até 120 chars")
    rationale: str = Field(description="Por que este gancho funciona para este público")


class ContentStrategyRecommendation(BaseModel):
    """
    Recomendação de estratégia de conteúdo gerada dinamicamente pelo Agno
    com base nos sinais de tendência capturados nas Camadas 0 e 1.

    Esta é a peça central da mudança arquitetural:
    em vez de um brand_context estático ditar o que publicar,
    o Agno analisa o que está em alta e RECOMENDA o melhor ângulo do dia.
    """
    # Classificação estratégica
    content_pillar:    ContentPillar   = Field(
        description="Pilar de conteúdo mais adequado para esta tendência")
    hospital_sector:   HospitalSector = Field(
        description="Setor hospitalar mais relevante para este momento")
    recommended_format: PostFormat    = Field(
        description="Formato sugerido pelo Agno com base no tipo de sinal")
    recommended_tone:   PostTone      = Field(
        description="Tom recomendado para este conteúdo e setor")

    # Ângulo narrativo
    narrative_angle:   str = Field(
        description="O ângulo da história em 1 frase — o que estamos contando e por quê agora")
    hook_options:      List[HookOption] = Field(
        min_length=2, max_length=3,
        description="2-3 opções de gancho para a primeira linha do caption")

    # Âncoras científicas (quando pilar == CIENCIA ou EDUCACAO)
    scientific_anchors: List[ScientificAnchor] = Field(
        default_factory=list, max_length=3,
        description="Dados científicos identificados para ancorar o post")

    # Sinais do nicho
    emerging_terms:    List[str] = Field(
        default_factory=list, max_length=10,
        description="Termos emergentes detectados especificamente no nicho MT/saúde")
    trending_hashtags: List[str] = Field(
        default_factory=list, max_length=20,
        description="Hashtags em alta neste nicho nas últimas 24h")

    # Guardrails éticos contextuais (gerados dinamicamente para ESTE conteúdo)
    ethical_risks:     List[str] = Field(
        default_factory=list,
        description="Riscos éticos específicos identificados para este ângulo (UBAM + ABMT)")
    requires_tcle:     bool = Field(
        default=False,
        description="True se o conteúdo recomendado envolve relato de caso ou paciente")
    show_epi:          bool = Field(
        default=False,
        description="True se o setor exige EPI visível nas imagens (UTI, oncologia, etc.)")

    # Justificativa da recomendação
    strategy_rationale: str = Field(
        description="Por que o Agno recomenda este pilar+setor+ângulo hoje — "
                    "conectando o sinal de tendência ao contexto clínico")


# ─── BrandIdentity (SSM — estático, raramente muda) ──────────────────────────

class BrandIdentity(BaseModel):
    """
    Identidade imutável da marca — armazenada no SSM Parameter Store.
    Contém apenas o que NÃO muda de execução para execução:
    voz, valores, ética, identificação profissional, restrições permanentes.

    NÃO contém mais: pilares de conteúdo, setores, ângulos, hashtags do dia.
    Esses elementos agora vêm do ContentStrategyRecommendation gerado pelo Agno.
    """
    brand_name:             str
    professional_id:        str = Field(
        description="Identificação da profissional: 'Mt. [Nome] — Musicoterapeuta ([nº registro])'")
    brand_voice:            str = Field(
        description="Tom e personalidade da marca em 2-3 frases")
    brand_values:           List[str] = Field(min_length=1, max_length=5)
    target_audience:        str

    # Restrições éticas permanentes — UBAM (2018) + ABMT (2025)
    ethical_frameworks:     List[str] = Field(
        description="Referências normativas que regem toda publicação")
    forbidden_language:     List[str] = Field(
        description="Palavras e expressões NUNCA permitidas (ex: 'cura', 'garante')")
    required_disclaimers:   Dict[str, str] = Field(
        default_factory=dict,
        description="Disclaimers obrigatórios por tipo de conteúdo: "
                    "{'case_report': 'texto do aviso', 'tcle': 'texto do aviso'}")
    competitor_handles:     List[str] = Field(default_factory=list)

    # Contexto geral da prática
    clinical_context:       str = Field(
        description="Descrição do contexto clínico e institucional da profissional")


# ─── TrendPayload (Agno → Bridge) — EXPANDIDO ────────────────────────────────

class InfluencerSignal(BaseModel):
    handle:          str
    platform:        Platform
    reach:           int   = Field(ge=0)
    engagement_rate: float = Field(ge=0.0, le=1.0)
    content_sample:  str   = Field(default="",
        description="Resumo anonimizado do conteúdo que está performando")


class PlatformSignal(BaseModel):
    platform:           Platform
    topic:              str
    volume_score:       float      = Field(ge=0.0, le=1.0)
    growth_rate:        float      = Field(description="% crescimento nas últimas 24h")
    sentiment:          Sentiment
    top_hashtags:       List[str]  = Field(default_factory=list, max_length=30)
    sample_content:     List[str]  = Field(default_factory=list, max_length=5)
    influencer_signals: List[InfluencerSignal] = Field(default_factory=list)


class TrendPayload(BaseModel):
    """
    Output do Agno Media Trend Analysis Agent — expandido na v2.

    NOVO: campo `content_strategy` com a recomendação gerada dinamicamente
    pelo Agno após analisar os sinais das Camadas 0 e 1.
    """
    trend_id:    str      = Field(default_factory=lambda: str(uuid.uuid4()))
    captured_at: datetime = Field(default_factory=datetime.utcnow)

    # Sinal bruto de tendência (inalterado da v1)
    consolidated_topic:           str           = Field(
        description="Descrição em 1 linha da tendência identificada")
    topic_keywords:               List[str]     = Field(min_length=3, max_length=20)
    trend_score:                  float         = Field(ge=0.0, le=1.0,
        description="(volume×0.4) + (min(growth,100)/100×0.4) + (sentiment==positive×0.2)")
    trend_category:               TrendCategory
    target_audience:              str
    context_summary:              str           = Field(
        description="2-3 frases: por que esta tendência importa AGORA")
    platform_signals:             List[PlatformSignal] = Field(min_length=1)
    similar_historical_trend_ids: List[str]     = Field(default_factory=list)

    # ── NOVO: Recomendação de estratégia de conteúdo ─────────────────────────
    content_strategy: ContentStrategyRecommendation = Field(
        description="Recomendação de pilar, setor, ângulo e gancho gerada pelo Agno "
                    "com base nos sinais das Camadas 0 e 1. "
                    "Este campo SUBSTITUI a lógica de estratégia que antes estava no SSM.")

    @field_validator("topic_keywords")
    @classmethod
    def keywords_lowercase(cls, v: List[str]) -> List[str]:
        return [kw.lower().strip() for kw in v]


# ─── ContextBrief (Bridge → CrewAI) — REFATORADO ─────────────────────────────

class PlatformInsights(BaseModel):
    top_hashtags:          List[str]       = Field(max_length=30)
    best_formats:          List[PostFormat]
    engagement_benchmarks: Dict[str, int]


class ContextBrief(BaseModel):
    """
    Input para o CrewAI — gerado pela Lambda Bridge via merge de:
      - BrandIdentity       (SSM — estático)
      - TrendPayload        (Agno — sinais brutos)
      - ContentStrategy     (Agno — recomendação estratégica)

    A separação é agora explícita nos campos do ContextBrief.
    O CrewAI recebe tudo que precisa sem ambiguidade sobre a origem de cada informação.
    """
    brief_id:     str      = Field(default_factory=lambda: str(uuid.uuid4()))
    trend_id:     str
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    # Identidade imutável da marca (do SSM)
    brand_identity:    BrandIdentity

    # Contexto da tendência (do Agno — sinais brutos)
    trend_context: "TrendContext"

    # Recomendação estratégica (do Agno — Camadas 0+1)
    content_strategy: ContentStrategyRecommendation

    # Requisitos técnicos do post
    post_requirements: "PostRequirements"


class TrendContext(BaseModel):
    topic:              str
    keywords:           List[str]
    trend_score:        float
    category:           TrendCategory
    context_summary:    str
    platform_insights:  PlatformInsights
    target_audience:    str


class PostRequirements(BaseModel):
    format:                    PostFormat
    caption_max_chars:         int  = Field(default=2200, le=2200)
    hashtag_limit:             int  = Field(default=30, le=30)
    max_hashtags_in_caption:   int  = Field(default=5)
    include_cta:               bool = True
    include_emoji:             bool = True
    language:                  str  = Field(default="pt-BR")


# ─── PostOutput (inalterado da v1) ────────────────────────────────────────────

class VisualBrief(BaseModel):
    primary_color_palette: List[str]
    visual_style:          str
    image_prompt:          str
    format_specs:          Dict[str, str]
    mood_references:       List[str] = Field(default_factory=list)
    production_notes:      str = ""


class PostOutput(BaseModel):
    post_id:                  str     = Field(default_factory=lambda: str(uuid.uuid4()))
    brief_id:                 str
    trend_id:                 str
    generated_at:             datetime = Field(default_factory=datetime.utcnow)
    caption:                  str      = Field(max_length=2200)
    hashtags:                 List[str] = Field(max_length=30)
    first_comment_hashtags:   List[str] = Field(default_factory=list)
    cta:                      str
    visual_brief:             VisualBrief
    readability_score:        Optional[float] = None
    brand_alignment_score:    Optional[float] = None

    # Metadados de rastreabilidade (novos na v2)
    content_pillar_used:   Optional[str] = None
    hospital_sector_used:  Optional[str] = None
    ethical_risks_flagged: List[str]     = Field(default_factory=list)

    @field_validator("caption")
    @classmethod
    def validate_caption_length(cls, v: str) -> str:
        if len(v) > 2200:
            raise ValueError(f"Caption {len(v)} chars > limite 2200")
        return v

    @field_validator("hashtags")
    @classmethod
    def sanitize_hashtags(cls, v: List[str]) -> List[str]:
        return [tag if tag.startswith("#") else f"#{tag}" for tag in v]


# Resolve forward references
ContextBrief.model_rebuild()
