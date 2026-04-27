"""
Schema consistency and Pydantic validation tests.

Catches mismatches between enum values defined in schemas.py and values
referenced in Lambda handlers — the class of bug that caused PostTone.INSPIRATIONAL
to crash the image-gen Lambda in production.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from schemas import (
    ContentPillar,
    ContentStrategyRecommendation,
    HookOption,
    HospitalSector,
    Platform,
    PlatformSignal,
    PostFormat,
    PostOutput,
    PostTone,
    Sentiment,
    TrendCategory,
    TrendPayload,
    VisualBrief,
)

HANDLERS_DIR = Path(__file__).parent.parent


# ─── Enum completeness ────────────────────────────────────────────────────────

class TestEnumConsistency:
    """Values used in handler source must match what is defined in schemas.py."""

    def _enum_refs_in_file(self, path: Path, enum_name: str) -> set[str]:
        """Extract all Enum.VALUE references from a source file."""
        source = path.read_text(encoding="utf-8")
        pattern = rf"{re.escape(enum_name)}\.(\w+)"
        return set(re.findall(pattern, source))

    def test_post_tone_in_image_gen_all_exist(self):
        """Every PostTone.X used in image_gen/lambda_handler.py must exist in PostTone."""
        handler = HANDLERS_DIR / "image_gen" / "lambda_handler.py"
        used = self._enum_refs_in_file(handler, "PostTone")
        defined = {e.name for e in PostTone}
        unknown = used - defined - {"value"}  # .value is a property call, not an enum member
        assert not unknown, f"PostTone names used in image_gen but missing from enum: {unknown}"

    def test_post_tone_image_gen_full_coverage(self):
        """TONE_TO_DALLE_STYLE in image_gen must cover ALL PostTone values (no silent fallback)."""
        handler = HANDLERS_DIR / "image_gen" / "lambda_handler.py"
        source = handler.read_text(encoding="utf-8")
        # Extract keys of TONE_TO_DALLE_STYLE block
        used = set(re.findall(r"PostTone\.(\w+)\.value", source))
        defined = {e.name for e in PostTone}
        uncovered = defined - used
        assert not uncovered, (
            f"PostTone values not covered by TONE_TO_DALLE_STYLE: {uncovered}. "
            "Add them to the map in image_gen/lambda_handler.py."
        )

    def test_post_format_in_publish_all_exist(self):
        handler = HANDLERS_DIR / "publish" / "lambda_handler.py"
        used = self._enum_refs_in_file(handler, "PostFormat")
        defined = {e.name for e in PostFormat}
        unknown = used - defined - {"value"}
        assert not unknown, f"PostFormat names used in publish but missing from enum: {unknown}"

    def test_content_pillar_in_fallback_all_exist(self):
        handler = HANDLERS_DIR / "fallback" / "lambda_handler.py"
        used = self._enum_refs_in_file(handler, "ContentPillar")
        defined = {e.name for e in ContentPillar}
        unknown = used - defined - {"value"}
        assert not unknown, f"ContentPillar names used in fallback but missing from enum: {unknown}"

    def test_hospital_sector_in_fallback_all_exist(self):
        handler = HANDLERS_DIR / "fallback" / "lambda_handler.py"
        used = self._enum_refs_in_file(handler, "HospitalSector")
        defined = {e.name for e in HospitalSector}
        unknown = used - defined - {"value"}
        assert not unknown, f"HospitalSector names used in fallback but missing from enum: {unknown}"

    def test_all_enum_values_are_lowercase_strings(self):
        """All str enums must have lowercase string values (JSON serialization contract)."""
        for enum_cls in (PostTone, PostFormat, ContentPillar, HospitalSector):
            for member in enum_cls:
                assert isinstance(member.value, str), f"{enum_cls.__name__}.{member.name} is not a string"
                assert member.value == member.value.lower(), (
                    f"{enum_cls.__name__}.{member.name} = '{member.value}' is not lowercase"
                )


# ─── HookOption validation ────────────────────────────────────────────────────

class TestHookOptionValidation:
    def test_text_at_limit_valid(self):
        hook = HookOption(text="A" * 120, rationale="test")
        assert len(hook.text) == 120

    def test_text_over_limit_raises(self):
        with pytest.raises(ValidationError, match="120"):
            HookOption(text="A" * 121, rationale="test")

    def test_text_empty_valid(self):
        hook = HookOption(text="", rationale="test")
        assert hook.text == ""


# ─── ContentStrategyRecommendation validation ─────────────────────────────────

class TestContentStrategyValidation:
    def _base_kwargs(self) -> dict:
        return dict(
            content_pillar=ContentPillar.CIENCIA,
            hospital_sector=HospitalSector.GERAL,
            recommended_format=PostFormat.FEED,
            recommended_tone=PostTone.SCIENTIFIC,
            narrative_angle="test",
            scientific_anchors=[],
            emerging_terms=[],
            trending_hashtags=[],
            ethical_risks=[],
            requires_tcle=False,
            show_epi=False,
            strategy_rationale="test",
        )

    def test_two_hooks_valid(self):
        kw = self._base_kwargs()
        kw["hook_options"] = [
            HookOption(text="hook1", rationale="r"),
            HookOption(text="hook2", rationale="r"),
        ]
        strategy = ContentStrategyRecommendation(**kw)
        assert len(strategy.hook_options) == 2

    def test_one_hook_raises(self):
        kw = self._base_kwargs()
        kw["hook_options"] = [HookOption(text="only one", rationale="r")]
        with pytest.raises(ValidationError):
            ContentStrategyRecommendation(**kw)

    def test_four_hooks_raises(self):
        kw = self._base_kwargs()
        kw["hook_options"] = [HookOption(text=f"hook{i}", rationale="r") for i in range(4)]
        with pytest.raises(ValidationError):
            ContentStrategyRecommendation(**kw)

    def test_requires_tcle_defaults_false(self):
        kw = self._base_kwargs()
        kw["hook_options"] = [
            HookOption(text="h1", rationale="r"),
            HookOption(text="h2", rationale="r"),
        ]
        strategy = ContentStrategyRecommendation(**kw)
        assert strategy.requires_tcle is False


# ─── TrendPayload validation ──────────────────────────────────────────────────

class TestTrendPayloadValidation:
    def test_content_strategy_required(self):
        """TrendPayload must include content_strategy — missing it must raise."""
        with pytest.raises(ValidationError):
            TrendPayload(
                trend_id="x",
                captured_at=datetime(2026, 1, 1),
                consolidated_topic="test",
                topic_keywords=["a", "b", "c"],
                trend_score=0.7,
                trend_category=TrendCategory.SCIENCE,
                target_audience="test",
                context_summary="test",
                platform_signals=[
                    PlatformSignal(
                        platform=Platform.INSTAGRAM, topic="t",
                        volume_score=0.5, growth_rate=10.0, sentiment=Sentiment.POSITIVE,
                    )
                ],
                # content_strategy intentionally omitted
            )

    def test_trend_score_above_1_raises(self, minimal_trend_payload):
        data = minimal_trend_payload.model_dump(mode="json")
        data["trend_score"] = 1.5
        with pytest.raises(ValidationError):
            TrendPayload.model_validate(data)

    def test_trend_score_below_0_raises(self, minimal_trend_payload):
        data = minimal_trend_payload.model_dump(mode="json")
        data["trend_score"] = -0.1
        with pytest.raises(ValidationError):
            TrendPayload.model_validate(data)

    def test_fewer_than_3_keywords_raises(self, minimal_trend_payload):
        data = minimal_trend_payload.model_dump(mode="json")
        data["topic_keywords"] = ["only_two", "keywords"]
        with pytest.raises(ValidationError):
            TrendPayload.model_validate(data)

    def test_valid_payload_round_trips(self, minimal_trend_payload):
        dumped = minimal_trend_payload.model_dump(mode="json")
        restored = TrendPayload.model_validate(dumped)
        assert restored.trend_id == minimal_trend_payload.trend_id
        assert restored.content_strategy.content_pillar == minimal_trend_payload.content_strategy.content_pillar


# ─── PostOutput validation ────────────────────────────────────────────────────

class TestPostOutputValidation:
    def test_caption_at_limit_valid(self, minimal_visual_brief):
        post = PostOutput(
            post_id="x", brief_id="x", trend_id="x",
            generated_at=datetime(2026, 1, 1),
            caption="A" * 2200,
            hashtags=[], cta="test",
            visual_brief=minimal_visual_brief,
        )
        assert len(post.caption) == 2200

    def test_caption_over_limit_raises(self, minimal_visual_brief):
        with pytest.raises(ValidationError):
            PostOutput(
                post_id="x", brief_id="x", trend_id="x",
                generated_at=datetime(2026, 1, 1),
                caption="A" * 2201,
                hashtags=[], cta="test",
                visual_brief=minimal_visual_brief,
            )

    def test_valid_post_round_trips(self, minimal_post_output):
        dumped = minimal_post_output.model_dump(mode="json")
        restored = PostOutput.model_validate(dumped)
        assert restored.post_id == minimal_post_output.post_id
