"""
Lambda handler contract tests.

Verifies that:
1. Core business logic functions work correctly with valid / invalid input
2. Handlers return the expected shape (keys + status) without calling AWS
3. The fallback default payload is a valid TrendPayload

AWS clients (boto3, openai, httpx) are patched at import time.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from schemas import PostTone, TrendPayload


# ─── Fallback handler ─────────────────────────────────────────────────────────

def _boto3_mocks() -> dict:
    """Return sys.modules patches for boto3 and its submodules."""
    m = MagicMock()
    return {
        "boto3": m,
        "boto3.dynamodb": m.dynamodb,
        "boto3.dynamodb.conditions": m.dynamodb.conditions,
        "boto3.dynamodb.table": m.dynamodb.table,
    }


class TestFallbackHandler:
    @pytest.fixture(autouse=True)
    def _patch_aws(self):
        mocks = _boto3_mocks()
        with patch.dict("sys.modules", mocks):
            for mod in list(sys.modules.keys()):
                if mod.startswith("fallback"):
                    del sys.modules[mod]
            yield
        for mod in list(sys.modules.keys()):
            if mod.startswith("fallback"):
                del sys.modules[mod]

    def test_default_payload_is_valid_trend_payload(self):
        from fallback.lambda_handler import _default_payload
        payload = _default_payload("musicoterapia hospitalar")
        assert isinstance(payload, TrendPayload)
        assert 0.0 <= payload.trend_score <= 1.0
        assert len(payload.topic_keywords) >= 3
        assert payload.content_strategy is not None

    def test_default_payload_has_two_hooks(self):
        from fallback.lambda_handler import _default_payload
        payload = _default_payload("musicoterapia hospitalar")
        hooks = payload.content_strategy.hook_options
        assert 2 <= len(hooks) <= 3

    def test_default_payload_hooks_under_120_chars(self):
        from fallback.lambda_handler import _default_payload
        payload = _default_payload("musicoterapia hospitalar")
        for hook in payload.content_strategy.hook_options:
            assert len(hook.text) <= 120, f"Hook too long: {hook.text!r}"

    def test_handler_returns_trend_payload_key(self):
        from fallback import lambda_handler as fh
        with patch.object(fh, "_query_cache", return_value=None):
            result = fh.lambda_handler({"niche": "musicoterapia hospitalar"}, None)
        assert "trend_payload" in result
        assert result["status"] in ("ok", "fallback")

    def test_returned_payload_is_valid(self):
        from fallback import lambda_handler as fh
        with patch.object(fh, "_query_cache", return_value=None):
            result = fh.lambda_handler({"niche": "musicoterapia hospitalar"}, None)
        TrendPayload.model_validate(result["trend_payload"])


# ─── Bridge handler ───────────────────────────────────────────────────────────

class TestBridgeHandler:
    @pytest.fixture(autouse=True)
    def _patch_aws(self):
        mocks = _boto3_mocks()
        with patch.dict("sys.modules", mocks):
            for mod in list(sys.modules.keys()):
                if mod.startswith("bridge"):
                    del sys.modules[mod]
            yield
        for mod in list(sys.modules.keys()):
            if mod.startswith("bridge"):
                del sys.modules[mod]

    def test_missing_trend_payload_returns_error(self):
        from bridge import lambda_handler as bh
        result = bh.lambda_handler({"brand_id": "musicoterapia-hospitalar"}, None)
        assert result["status"] == "error"

    def test_valid_payload_with_default_brand_returns_ok(self, minimal_trend_payload):
        from bridge import lambda_handler as bh
        with patch.object(bh, "_load_brand_identity", side_effect=Exception("SSM unavailable")):
            result = bh.lambda_handler(
                {
                    "trend_payload": minimal_trend_payload.model_dump(mode="json"),
                    "brand_id": "musicoterapia-hospitalar",
                    "post_format": "feed",
                    "language": "pt-BR",
                },
                None,
            )
        assert result["status"] == "ok"

    def test_ok_response_has_all_required_keys(self, minimal_trend_payload):
        from bridge import lambda_handler as bh
        with patch.object(bh, "_load_brand_identity", side_effect=Exception("SSM")):
            result = bh.lambda_handler(
                {
                    "trend_payload": minimal_trend_payload.model_dump(mode="json"),
                    "brand_id": "musicoterapia-hospitalar",
                    "post_format": "feed",
                    "language": "pt-BR",
                },
                None,
            )
        if result["status"] == "ok":
            for key in ("context_brief", "brief_id", "trend_id", "requires_tcle", "show_epi"):
                assert key in result, f"Missing key in bridge response: {key}"

    def test_context_brief_contains_content_strategy(self, minimal_trend_payload):
        from bridge import lambda_handler as bh
        with patch.object(bh, "_load_brand_identity", side_effect=Exception("SSM")):
            result = bh.lambda_handler(
                {
                    "trend_payload": minimal_trend_payload.model_dump(mode="json"),
                    "brand_id": "musicoterapia-hospitalar",
                    "post_format": "feed",
                    "language": "pt-BR",
                },
                None,
            )
        if result["status"] == "ok":
            cs = result["context_brief"]["content_strategy"]
            assert "requires_tcle" in cs
            assert "show_epi" in cs

    def test_requires_tcle_matches_content_strategy(self, minimal_trend_payload):
        """bridge_result.requires_tcle must equal context_brief.content_strategy.requires_tcle."""
        from bridge import lambda_handler as bh
        with patch.object(bh, "_load_brand_identity", side_effect=Exception("SSM")):
            result = bh.lambda_handler(
                {
                    "trend_payload": minimal_trend_payload.model_dump(mode="json"),
                    "brand_id": "musicoterapia-hospitalar",
                    "post_format": "feed",
                    "language": "pt-BR",
                },
                None,
            )
        if result["status"] == "ok":
            assert result["requires_tcle"] == result["context_brief"]["content_strategy"]["requires_tcle"]


# ─── CrewAI handler ───────────────────────────────────────────────────────────

class TestCrewAIHandler:
    """Tests that don't invoke the actual LLM — only handler input/output contract."""

    @pytest.fixture(autouse=True)
    def _patch_crewai(self):
        mocks = {
            "crewai": MagicMock(),
            "crewai.tools": MagicMock(),
            "crewai_tools": MagicMock(),
            "langchain_anthropic": MagicMock(),
            "agentops": MagicMock(),
        }
        # Remove cached modules so patches apply on re-import
        for mod in list(sys.modules.keys()):
            if mod.startswith("crewai_crew"):
                del sys.modules[mod]
        with patch.dict("sys.modules", mocks):
            yield
        for mod in list(sys.modules.keys()):
            if mod.startswith("crewai_crew"):
                del sys.modules[mod]

    def test_missing_context_brief_returns_error(self):
        from crewai_crew import instagram_crew
        result = instagram_crew.lambda_handler({}, None)
        assert result["status"] == "error"
        assert "context_brief" in result.get("detail", "").lower()

    def test_handler_is_callable(self):
        from crewai_crew import instagram_crew
        assert callable(instagram_crew.lambda_handler)


# ─── Image-gen handler ────────────────────────────────────────────────────────

class TestImageGenHandler:
    @pytest.fixture(autouse=True)
    def _patch_aws_and_openai(self):
        tenacity_mock = MagicMock()
        tenacity_mock.retry = lambda *a, **kw: (lambda f: f)
        tenacity_mock.retry_if_exception_type = MagicMock(return_value=MagicMock())
        tenacity_mock.stop_after_attempt = MagicMock(return_value=MagicMock())
        tenacity_mock.wait_exponential = MagicMock(return_value=MagicMock())
        mocks = {
            **_boto3_mocks(),
            "openai": MagicMock(),
            "httpx": MagicMock(),
            "tenacity": tenacity_mock,
        }
        with patch.dict("sys.modules", mocks):
            for mod in list(sys.modules.keys()):
                if mod.startswith("image_gen"):
                    del sys.modules[mod]
            yield
        for mod in list(sys.modules.keys()):
            if mod.startswith("image_gen"):
                del sys.modules[mod]

    def test_tone_to_dalle_style_covers_all_post_tones(self):
        """Regression: PostTone.INSPIRATIONAL crashed production."""
        from image_gen import lambda_handler as igh
        defined = {t.value for t in PostTone}
        mapped = set(igh.TONE_TO_DALLE_STYLE.keys())
        missing = defined - mapped
        assert not missing, f"PostTone values missing from TONE_TO_DALLE_STYLE: {missing}"

    def test_tone_to_dalle_style_has_no_unknown_keys(self):
        from image_gen import lambda_handler as igh
        defined = {t.value for t in PostTone}
        mapped = set(igh.TONE_TO_DALLE_STYLE.keys())
        unknown = mapped - defined
        assert not unknown, f"Unknown values in TONE_TO_DALLE_STYLE: {unknown}"

    def test_dalle_style_values_are_valid(self):
        from image_gen import lambda_handler as igh
        valid_styles = {"vivid", "natural"}
        for tone, style in igh.TONE_TO_DALLE_STYLE.items():
            assert style in valid_styles, f"Invalid DALL-E style '{style}' for tone '{tone}'"

    def test_missing_post_output_returns_error(self):
        from image_gen import lambda_handler as igh
        result = igh.lambda_handler({"post_format": "feed", "n_slides": 1}, None)
        assert result["status"] == "error"


# ─── Publish handler ─────────────────────────────────────────────────────────

class TestPublishHandler:
    @pytest.fixture(autouse=True)
    def _patch_aws(self):
        tenacity_mock = MagicMock()
        tenacity_mock.retry = lambda *a, **kw: (lambda f: f)
        tenacity_mock.retry_if_exception_type = MagicMock(return_value=MagicMock())
        tenacity_mock.stop_after_attempt = MagicMock(return_value=MagicMock())
        tenacity_mock.wait_exponential = MagicMock(return_value=MagicMock())
        mocks = {
            **_boto3_mocks(),
            "httpx": MagicMock(),
            "tenacity": tenacity_mock,
        }
        with patch.dict("sys.modules", mocks):
            for mod in list(sys.modules.keys()):
                if mod.startswith("publish"):
                    del sys.modules[mod]
            yield
        for mod in list(sys.modules.keys()):
            if mod.startswith("publish"):
                del sys.modules[mod]

    def test_missing_instagram_account_id_returns_error(self, minimal_post_output):
        from publish import lambda_handler as ph
        result = ph.lambda_handler(
            {
                "post_output": minimal_post_output.model_dump(mode="json"),
                "asset_url": "https://example.com/img.jpg",
                "asset_urls": [],
            },
            None,
        )
        assert result["status"] == "error"

    def test_build_caption_includes_caption_text(self, minimal_post_output):
        from publish.lambda_handler import InstagramPublisher
        caption = InstagramPublisher._build_caption(minimal_post_output)
        assert minimal_post_output.caption in caption

    def test_build_caption_includes_cta(self, minimal_post_output):
        from publish.lambda_handler import InstagramPublisher
        caption = InstagramPublisher._build_caption(minimal_post_output)
        assert minimal_post_output.cta in caption

    def test_build_caption_includes_hashtags(self, minimal_post_output):
        from publish.lambda_handler import InstagramPublisher
        caption = InstagramPublisher._build_caption(minimal_post_output)
        for tag in minimal_post_output.hashtags:
            assert tag in caption

    def test_resolve_media_type_feed_is_image(self):
        from publish.lambda_handler import InstagramPublisher
        from schemas import PostFormat
        media_type = InstagramPublisher._resolve_media_type(PostFormat.FEED)
        assert media_type.upper() in ("IMAGE", "FEED")

    def test_resolve_media_type_reel_is_reels(self):
        from publish.lambda_handler import InstagramPublisher
        from schemas import PostFormat
        media_type = InstagramPublisher._resolve_media_type(PostFormat.REEL)
        assert "REEL" in media_type.upper()
