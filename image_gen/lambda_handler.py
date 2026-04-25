"""
image_gen_lambda.py
───────────────────
Generates post images from the CrewAI VisualBrief and uploads them to S3,
returning public (or pre-signed) URLs ready for the Instagram Graph API.

Providers (in priority order):
  1. OpenAI DALL-E 3  — primary, highest quality
  2. Amazon Titan Image Generator v2 (Bedrock) — fallback, no extra API key

Supported formats:
  • feed    (IMAGE)   → single image, 4:5 or 1:1
  • story   (STORIES) → single image, 9:16
  • reel    (REELS)   → thumbnail image only (video handled separately)
  • carousel          → N images generated as sequential variations

Flow per execution:
  1. Parse PostOutput from event
  2. Build enriched prompt from VisualBrief
  3. Resolve dimensions from format_specs.aspect_ratio
  4. Generate image(s) — DALL-E 3 first, Titan on failure
  5. Upload raw bytes to S3
  6. Return asset_url / asset_urls to Step Functions

Entry-point: lambda_handler(event, context) → dict

Expected event (from Step Functions GenerateImage state):
{
    "post_output":  { ...PostOutput fields... },
    "post_format":  "feed" | "story" | "reel" | "carousel",
    "n_slides":     3         // carousel only — default 3, max 10
}
"""
from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import boto3
import httpx
from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from schemas import PostFormat, PostOutput, PostTone

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ── AWS / config ──────────────────────────────────────────────────────────────
s3              = boto3.client("s3",       region_name=os.getenv("AWS_REGION", "us-east-1"))
bedrock         = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))
secrets_client  = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))

IMAGE_BUCKET     = os.getenv("IMAGE_BUCKET", "pulsocast-assets")
S3_PREFIX        = os.getenv("S3_PREFIX", "generated-images")
S3_URL_TYPE      = os.getenv("S3_URL_TYPE", "presigned")  # "presigned" | "public"
PRESIGNED_TTL    = int(os.getenv("PRESIGNED_TTL_SECONDS", "3600"))  # 1 h default
OPENAI_SECRET    = os.getenv("OPENAI_SECRET_NAME", "/pulsocast/openai-api-key")
TITAN_MODEL_ID   = "amazon.titan-image-generator-v2:0"
MAX_WORKERS      = 3  # max parallel image generations for carousel

# In-memory API key cache
_openai_key_cache: str | None = None


# ─── Dimension tables ─────────────────────────────────────────────────────────

# DALL-E 3 only supports three sizes — map aspect ratios to the closest
DALLE_SIZES: dict[str, str] = {
    "1:1":  "1024x1024",
    "4:5":  "1024x1024",   # 4:5 not natively supported; Instagram crops from 1:1
    "9:16": "1024x1792",
    "16:9": "1792x1024",
}

# Titan Image Generator v2 supports more granular sizes
TITAN_SIZES: dict[str, tuple[int, int]] = {
    "1:1":  (1024, 1024),
    "4:5":  (768,  960),   # exact 4:5 ✓
    "9:16": (768,  1280),  # exact 9:16 ✓
    "16:9": (1280, 768),
}

# Tone → DALL-E style (vivid = dramatic, natural = realistic/calm)
TONE_TO_DALLE_STYLE: dict[str, str] = {
    PostTone.INSPIRATIONAL.value:  "vivid",
    PostTone.HUMOROUS.value:       "vivid",
    PostTone.PROVOCATIVE.value:    "vivid",
    PostTone.EDUCATIONAL.value:    "natural",
    PostTone.EMPATHETIC.value:     "natural",
    PostTone.AUTHORITATIVE.value:  "natural",
}


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class GenerationRequest:
    prompt:       str
    aspect_ratio: str
    style:        str        # "vivid" | "natural" (DALL-E param)
    slide_index:  int = 0    # 0 for single images; 1-N for carousel slides


@dataclass
class GeneratedImage:
    s3_key:  str
    url:     str
    provider: str  # "dalle3" | "titan"


# ─── Custom exceptions ────────────────────────────────────────────────────────

class ImageGenError(Exception):
    """Base exception for image generation failures."""

class DalleRateLimitError(ImageGenError):
    """HTTP 429 from OpenAI — triggers tenacity retry with backoff."""

class DalleContentFilterError(ImageGenError):
    """DALL-E content policy rejection — do not retry, fall back to Titan."""


# ─── Lambda entry-point ───────────────────────────────────────────────────────

def lambda_handler(event: dict, context: Any) -> dict:
    """
    AWS Lambda entry-point.

    Returns:
        Single-asset  → { "status": "ok", "asset_url": str,         "post_format": str }
        Carousel      → { "status": "ok", "asset_urls": list[str],  "post_format": str }
    """
    logger.info("ImageGen Lambda invoked", extra={"keys": list(event.keys())})

    try:
        raw_output  = event.get("post_output")
        if not raw_output:
            raise ValueError("Missing 'post_output' in event")

        post        = PostOutput.model_validate(raw_output)
        post_format = PostFormat(event.get("post_format", "feed"))
        n_slides    = min(int(event.get("n_slides", 3)), 10)

        generator   = ImageGenerator(post=post, post_format=post_format)

        if post_format == PostFormat.CAROUSEL:
            images  = generator.generate_carousel(n_slides=n_slides)
            return {
                "status":      "ok",
                "asset_urls":  [img.url for img in images],
                "post_format": post_format.value,
                "provider":    images[0].provider if images else "unknown",
            }
        else:
            image   = generator.generate_single()
            return {
                "status":      "ok",
                "asset_url":   image.url,
                "post_format": post_format.value,
                "provider":    image.provider,
            }

    except ValidationError as exc:
        logger.error(f"Schema validation failed: {exc.json()}")
        return {"status": "error", "error_type": "validation", "detail": exc.errors()}
    except ImageGenError as exc:
        logger.error(f"Image generation failed: {exc}")
        return {"status": "error", "error_type": "image_gen", "detail": str(exc)}
    except Exception as exc:
        logger.exception("Unhandled error in ImageGen Lambda")
        return {"status": "error", "error_type": "internal", "detail": str(exc)}


# ─── Core generator ───────────────────────────────────────────────────────────

class ImageGenerator:
    """
    Orchestrates image generation and S3 upload for a given PostOutput.
    Tries DALL-E 3 first; falls back to Amazon Titan v2 automatically.
    """

    def __init__(self, post: PostOutput, post_format: PostFormat) -> None:
        self.post        = post
        self.post_format = post_format
        self.vb          = post.visual_brief

    # ── Public methods ────────────────────────────────────────────────────────

    def generate_single(self) -> GeneratedImage:
        """Generate one image for feed / story / reel thumbnail."""
        req = self._build_request(slide_index=0)
        return self._generate_and_upload(req)

    def generate_carousel(self, n_slides: int) -> list[GeneratedImage]:
        """
        Generate N images in parallel for a carousel post.
        Each slide gets a compositionally distinct variation of the base prompt.
        """
        requests = [self._build_request(slide_index=i) for i in range(1, n_slides + 1)]

        results: list[GeneratedImage | None] = [None] * len(requests)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(self._generate_and_upload, req): idx
                for idx, req in enumerate(requests)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                    logger.info(f"Carousel slide {idx+1}/{n_slides} done")
                except Exception as exc:
                    logger.error(f"Carousel slide {idx+1} failed: {exc}")
                    raise

        return [r for r in results if r is not None]

    # ── Request building ─────────────────────────────────────────────────────

    def _build_request(self, slide_index: int) -> GenerationRequest:
        """Assemble a GenerationRequest from the VisualBrief fields."""
        aspect_ratio = self._resolve_aspect_ratio()
        style        = self._resolve_dalle_style()
        prompt       = self._enrich_prompt(slide_index)

        return GenerationRequest(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            style=style,
            slide_index=slide_index,
        )

    def _resolve_aspect_ratio(self) -> str:
        """Extract aspect ratio from format_specs, defaulting by post format."""
        raw = self.vb.format_specs.get("aspect_ratio", "")
        # Normalise "4:5 (1080×1350 px)" → "4:5"
        clean = raw.split(" ")[0].strip()

        if clean in DALLE_SIZES:
            return clean

        defaults = {
            PostFormat.FEED:     "4:5",
            PostFormat.STORY:    "9:16",
            PostFormat.REEL:     "9:16",
            PostFormat.CAROUSEL: "4:5",
        }
        return defaults.get(self.post_format, "1:1")

    def _resolve_dalle_style(self) -> str:
        """Map PostTone to DALL-E style parameter."""
        # Try to infer tone from visual_style text
        vs = self.vb.visual_style.lower()
        if any(w in vs for w in ("bold", "vibrant", "dramatic", "energetic", "vivid")):
            return "vivid"
        return "natural"

    def _enrich_prompt(self, slide_index: int) -> str:
        """
        Build the final generation prompt from VisualBrief components.

        Layering strategy:
          base     = image_prompt (from Diretor Visual agent)
          + style  = visual_style adjectives
          + colors = primary_color_palette description
          + mood   = first mood_reference (if any)
          + notes  = production_notes constraints
          + slide  = per-slide compositional hint (carousel only)
        """
        parts: list[str] = [self.vb.image_prompt.strip()]

        # Visual style adjectives
        if self.vb.visual_style:
            parts.append(f"Overall visual style: {self.vb.visual_style}.")

        # Color palette
        if self.vb.primary_color_palette:
            palette = ", ".join(self.vb.primary_color_palette[:4])
            parts.append(f"Color palette: {palette}.")

        # Mood reference (only the first one to keep prompt focused)
        if self.vb.mood_references:
            parts.append(f"Aesthetic reference: {self.vb.mood_references[0]}.")

        # Production constraints (avoid list)
        if self.vb.production_notes:
            parts.append(f"Constraints: {self.vb.production_notes}")

        # Carousel slide-specific variation
        if slide_index > 0:
            slide_hints = [
                "Wide establishing shot, environmental context.",
                "Close-up detail, texture and materiality.",
                "Human element — hands, lifestyle interaction.",
                "Product or subject centered, minimal negative space.",
                "Overhead flat-lay composition.",
                "Side profile, depth of field, bokeh background.",
                "Silhouette against bright background.",
                "Macro detail, abstract crop.",
                "Dynamic angle, motion blur suggestion.",
                "Rule of thirds, leading lines.",
            ]
            hint = slide_hints[(slide_index - 1) % len(slide_hints)]
            parts.append(f"Composition for slide {slide_index}: {hint}")

        # Always append technical quality boosters
        parts.append(
            "Professional photography, high resolution, sharp focus, "
            "commercial quality, clean background, Instagram-ready."
        )

        return " ".join(parts)

    # ── Generation + upload ───────────────────────────────────────────────────

    def _generate_and_upload(self, req: GenerationRequest) -> GeneratedImage:
        """Try DALL-E 3 → fallback to Titan v2 → upload to S3."""
        image_bytes: bytes
        provider: str

        try:
            image_bytes = _dalle3_generate(req)
            provider    = "dalle3"
            logger.info(f"DALL-E 3 generation OK | slide={req.slide_index}")
        except (ImageGenError, Exception) as exc:
            logger.warning(f"DALL-E 3 failed ({exc}) — falling back to Titan v2")
            try:
                image_bytes = _titan_generate(req)
                provider    = "titan"
                logger.info(f"Titan v2 generation OK | slide={req.slide_index}")
            except Exception as fallback_exc:
                raise ImageGenError(
                    f"Both providers failed. "
                    f"DALL-E: {exc} | Titan: {fallback_exc}"
                ) from fallback_exc

        s3_key = _upload_to_s3(
            image_bytes=image_bytes,
            post_id=self.post.post_id,
            slide_index=req.slide_index,
        )
        url = _build_url(s3_key)

        return GeneratedImage(s3_key=s3_key, url=url, provider=provider)


# ─── DALL-E 3 provider ────────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type(DalleRateLimitError),
    wait=wait_exponential(multiplier=2, min=15, max=90),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _dalle3_generate(req: GenerationRequest) -> bytes:
    """
    Call OpenAI Images API (DALL-E 3) and return raw PNG bytes.

    Docs: https://platform.openai.com/docs/api-reference/images/create
    """
    api_key = _load_openai_key()
    size    = DALLE_SIZES.get(req.aspect_ratio, "1024x1024")

    payload = {
        "model":           "dall-e-3",
        "prompt":          req.prompt,
        "n":               1,
        "size":            size,
        "quality":         "hd",
        "style":           req.style,
        "response_format": "b64_json",
    }

    logger.debug(f"DALL-E 3 request | size={size} style={req.style} "
                 f"prompt_len={len(req.prompt)}")

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            json=payload,
        )

    if resp.status_code == 429:
        raise DalleRateLimitError("DALL-E 3 rate limit (429)")

    if resp.status_code == 400:
        detail = resp.json().get("error", {}).get("message", "")
        raise DalleContentFilterError(f"DALL-E 3 content policy rejection: {detail}")

    if resp.status_code != 200:
        raise ImageGenError(f"DALL-E 3 HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    b64  = data["data"][0]["b64_json"]
    return base64.b64decode(b64)


# ─── Amazon Titan v2 provider ─────────────────────────────────────────────────

def _titan_generate(req: GenerationRequest) -> bytes:
    """
    Call Amazon Titan Image Generator v2 via Bedrock and return raw PNG bytes.

    Docs: https://docs.aws.amazon.com/bedrock/latest/userguide/titan-image-models.html
    """
    w, h   = TITAN_SIZES.get(req.aspect_ratio, (1024, 1024))

    # Titan prompt is English-only; truncate at 512 chars (model limit)
    prompt = req.prompt[:512]

    body = json.dumps({
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {
            "text":              prompt,
            "negativeText":      (
                "blurry, low quality, distorted, watermark, text overlay, "
                "logo, ugly, deformed, noisy, oversaturated"
            ),
        },
        "imageGenerationConfig": {
            "width":          w,
            "height":         h,
            "quality":        "premium",
            "numberOfImages": 1,
            "cfgScale":       8.0,
            "seed":           0,
        },
    })

    logger.debug(f"Titan v2 request | {w}×{h} | prompt_len={len(prompt)}")

    response = bedrock.invoke_model(
        modelId=TITAN_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )

    result = json.loads(response["body"].read())

    if result.get("error"):
        raise ImageGenError(f"Titan v2 error: {result['error']}")

    b64 = result["images"][0]
    return base64.b64decode(b64)


# ─── S3 upload ────────────────────────────────────────────────────────────────

def _upload_to_s3(
    image_bytes: bytes,
    post_id: str,
    slide_index: int,
) -> str:
    """
    Upload PNG bytes to S3 and return the object key.
    Key format: {prefix}/{post_id}/slide-{N}-{uuid}.png
    """
    suffix  = f"slide-{slide_index}" if slide_index > 0 else "main"
    s3_key  = f"{S3_PREFIX}/{post_id}/{suffix}-{uuid.uuid4().hex[:8]}.png"

    extra_args: dict = {"ContentType": "image/png"}

    if S3_URL_TYPE == "public":
        extra_args["ACL"] = "public-read"

    s3.put_object(
        Bucket=IMAGE_BUCKET,
        Key=s3_key,
        Body=image_bytes,
        **extra_args,
    )

    logger.info(
        f"Image uploaded to S3 | "
        f"bucket={IMAGE_BUCKET} key={s3_key} size={len(image_bytes)} bytes"
    )
    return s3_key


def _build_url(s3_key: str) -> str:
    """
    Build the public or pre-signed URL for a given S3 key.

    Instagram Graph API REQUIRES the URL to be publicly accessible
    at the time the media container is created.

    Recommended production setup: CloudFront distribution in front of
    this S3 bucket → set S3_URL_TYPE=public and configure a CloudFront
    origin for IMAGE_BUCKET, then replace this function with:
        return f"https://{CLOUDFRONT_DOMAIN}/{s3_key}"
    """
    if S3_URL_TYPE == "public":
        region = os.getenv("AWS_REGION", "us-east-1")
        return f"https://{IMAGE_BUCKET}.s3.{region}.amazonaws.com/{s3_key}"

    # Pre-signed URL (default — valid for PRESIGNED_TTL seconds)
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": IMAGE_BUCKET, "Key": s3_key},
        ExpiresIn=PRESIGNED_TTL,
    )
    logger.debug(f"Pre-signed URL generated | ttl={PRESIGNED_TTL}s key={s3_key}")
    return url


# ─── Secrets ──────────────────────────────────────────────────────────────────

def _load_openai_key() -> str:
    """Load OpenAI API key from Secrets Manager (cached in-memory)."""
    global _openai_key_cache
    if _openai_key_cache:
        return _openai_key_cache

    try:
        resp   = secrets_client.get_secret_value(SecretId=OPENAI_SECRET)
        secret = json.loads(resp["SecretString"])
        key    = secret.get("api_key") or secret.get("OPENAI_API_KEY")

        if not key:
            raise ImageGenError(
                f"Secret '{OPENAI_SECRET}' does not contain 'api_key'"
            )

        _openai_key_cache = key
        logger.info("OpenAI API key loaded from Secrets Manager")
        return key

    except secrets_client.exceptions.ResourceNotFoundException:
        raise ImageGenError(f"Secret '{OPENAI_SECRET}' not found — Titan will be used")
