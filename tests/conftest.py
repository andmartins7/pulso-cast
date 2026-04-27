"""Shared fixtures for the PulsoCast test suite."""
from __future__ import annotations

from datetime import datetime

import pytest

from schemas import (
    ContentPillar,
    ContentStrategyRecommendation,
    ContextBrief,
    BrandIdentity,
    HookOption,
    HospitalSector,
    PlatformInsights,
    PlatformSignal,
    Platform,
    PostFormat,
    PostOutput,
    PostRequirements,
    PostTone,
    Sentiment,
    TrendCategory,
    TrendContext,
    TrendPayload,
    VisualBrief,
)


@pytest.fixture
def minimal_content_strategy() -> ContentStrategyRecommendation:
    return ContentStrategyRecommendation(
        content_pillar=ContentPillar.CIENCIA,
        hospital_sector=HospitalSector.UTI,
        recommended_format=PostFormat.FEED,
        recommended_tone=PostTone.SCIENTIFIC,
        narrative_angle="Como a musicoterapia apoia a reabilitação em UTI",
        hook_options=[
            HookOption(text="8 minutos de música transformam a UTI neonatal", rationale="Dado numérico"),
            HookOption(text="Evidências mostram: a música estabiliza parâmetros vitais", rationale="Âncora científica"),
        ],
        scientific_anchors=[],
        emerging_terms=["musicoterapia clínica"],
        trending_hashtags=["#musicoterapia"],
        ethical_risks=["Manter anonimato do paciente"],
        requires_tcle=False,
        show_epi=True,
        strategy_rationale="Pilar ciência com evidência robusta",
    )


@pytest.fixture
def minimal_trend_payload(minimal_content_strategy: ContentStrategyRecommendation) -> TrendPayload:
    return TrendPayload(
        trend_id="test-trend-001",
        captured_at=datetime(2026, 1, 1, 12, 0, 0),
        consolidated_topic="Musicoterapia em UTI neonatal",
        topic_keywords=["musicoterapia", "uti", "neonatal"],
        trend_score=0.75,
        trend_category=TrendCategory.SCIENCE,
        target_audience="Musicoterapeutas hospitalares",
        context_summary="Tendência de alta em musicoterapia hospitalar",
        platform_signals=[
            PlatformSignal(
                platform=Platform.INSTAGRAM,
                topic="musicoterapia",
                volume_score=0.7,
                growth_rate=30.0,
                sentiment=Sentiment.POSITIVE,
            )
        ],
        content_strategy=minimal_content_strategy,
    )


@pytest.fixture
def minimal_visual_brief() -> VisualBrief:
    return VisualBrief(
        primary_color_palette=["#FFFFFF", "#4A90A4"],
        visual_style="Fotografia clínica documental",
        image_prompt="Close-up de musicoterapeuta em UTI hospitalar com instrumento terapêutico",
        format_specs={"aspect_ratio": "4:5", "text_overlay": "false"},
    )


@pytest.fixture
def minimal_post_output(minimal_visual_brief: VisualBrief) -> PostOutput:
    return PostOutput(
        post_id="test-post-001",
        brief_id="test-brief-001",
        trend_id="test-trend-001",
        generated_at=datetime(2026, 1, 1, 12, 0, 0),
        caption=(
            "Evidências indicam que a musicoterapia contribui para a regulação emocional. "
            "Estudos mostram redução do estresse em pacientes de UTI. "
            "Mt. Teste — Musicoterapeuta (123)"
        ),
        hashtags=["#musicoterapia", "#utineonatal"],
        cta="Saiba mais sobre musicoterapia hospitalar nos comentários.",
        visual_brief=minimal_visual_brief,
    )


@pytest.fixture
def minimal_brand_identity() -> BrandIdentity:
    return BrandIdentity(
        brand_name="Musicoterapia Hospitalar",
        professional_id="Mt. Teste — Musicoterapeuta (123)",
        brand_voice="Tom humano, científico e esperançoso",
        brand_values=["evidência científica"],
        target_audience="Profissionais de saúde",
        ethical_frameworks=["UBAM 2018"],
        forbidden_language=["cura"],
        required_disclaimers={"case_report": "Autorização obtida."},
        competitor_handles=[],
        clinical_context="Contexto multiprofissional hospitalar",
    )


@pytest.fixture
def minimal_context_brief(
    minimal_brand_identity: BrandIdentity,
    minimal_content_strategy: ContentStrategyRecommendation,
    minimal_trend_payload: TrendPayload,
) -> ContextBrief:
    trend_context = TrendContext(
        topic=minimal_trend_payload.consolidated_topic,
        keywords=minimal_trend_payload.topic_keywords,
        trend_score=minimal_trend_payload.trend_score,
        category=minimal_trend_payload.trend_category,
        context_summary=minimal_trend_payload.context_summary,
        platform_insights=PlatformInsights(
            top_hashtags=["#musicoterapia"],
            best_formats=[PostFormat.FEED],
            engagement_benchmarks={"avg_likes": 100},
        ),
        target_audience=minimal_trend_payload.target_audience,
    )
    return ContextBrief(
        brief_id="test-brief-001",
        trend_id="test-trend-001",
        generated_at=datetime(2026, 1, 1, 12, 0, 0),
        brand_identity=minimal_brand_identity,
        trend_context=trend_context,
        content_strategy=minimal_content_strategy,
        post_requirements=PostRequirements(
            format=PostFormat.FEED,
            include_cta=True,
            include_emoji=True,
        ),
    )
