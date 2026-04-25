"""
publish_lambda.py
─────────────────
Instagram Graph API publisher Lambda.

Responsibilities (in order):
  1. Load IG access token from Secrets Manager
  2. Build the media container for the correct post format
     (IMAGE feed/story, REEL, CAROUSEL — each has its own API flow)
  3. Poll until container status == FINISHED
  4. Publish the container → get instagram_media_id
  5. Post the first comment with overflow hashtags
  6. Persist publish record to DynamoDB (audit + metrics)
  7. Return instagram_post_id + published_at + permalink

Entry-point: lambda_handler(event, context) → dict

Expected event (from Step Functions PublishPost state):
{
    "post_output": { ...PostOutput fields... },
    "instagram_account_id": "17841400000000000",

    // Media assets — pre-uploaded to a public URL or S3 pre-signed URL
    // Required for IMAGE/STORY/REEL formats.
    // For CAROUSEL, provide a list.
    "asset_url":  "https://cdn.example.com/post-image.jpg",     // single asset
    "asset_urls": ["https://cdn.example.com/slide-1.jpg", ...], // carousel

    // Optional overrides
    "scheduled_publish_time": null  // ISO8601 — null means publish immediately
}
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import boto3
import httpx
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from schemas import PostFormat, PostOutput

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ── AWS clients ───────────────────────────────────────────────────────────────
secrets_client  = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
dynamodb        = boto3.resource("dynamodb",      region_name=os.getenv("AWS_REGION", "us-east-1"))

# ── Constants ─────────────────────────────────────────────────────────────────
GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE    = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
PUBLISH_TABLE     = os.getenv("PUBLISH_TABLE", "pulsocast-publish-log")
SECRET_NAME       = os.getenv("IG_TOKEN_SECRET", "/pulsocast/ig-access-token")

# Container status polling
POLL_MAX_ATTEMPTS  = 30
POLL_INTERVAL_SEC  = 5
CONTAINER_FINISHED = "FINISHED"
CONTAINER_ERROR    = "ERROR"

# In-memory token cache (warm Lambda invocations)
_token_cache: dict[str, str] = {}


# ─── Lambda entry-point ───────────────────────────────────────────────────────

def lambda_handler(event: dict, context: Any) -> dict:
    """
    AWS Lambda entry-point invoked by Step Functions PublishPost state.
    """
    logger.info("Publisher Lambda invoked", extra={"keys": list(event.keys())})

    try:
        # ── 1. Parse and validate inputs ──────────────────────────────────
        raw_output = event.get("post_output")
        if not raw_output:
            raise ValueError("Missing 'post_output' in event")

        post       = PostOutput.model_validate(raw_output)
        account_id = event["instagram_account_id"]
        asset_url  = event.get("asset_url")
        asset_urls = event.get("asset_urls", [])

        post_format = PostFormat(post.visual_brief.format_specs.get("format", "feed"))

        # ── 2. Load access token ──────────────────────────────────────────
        access_token = _load_access_token(account_id)

        # ── 3. Build + publish media container ───────────────────────────
        publisher = InstagramPublisher(
            account_id=account_id,
            access_token=access_token,
        )

        ig_media_id, permalink = publisher.publish(
            post=post,
            post_format=post_format,
            asset_url=asset_url,
            asset_urls=asset_urls,
        )

        published_at = datetime.now(timezone.utc).isoformat()

        # ── 4. Post first comment (overflow hashtags) ─────────────────────
        comment_id = None
        if post.first_comment_hashtags:
            comment_id = publisher.post_first_comment(
                media_id=ig_media_id,
                hashtags=post.first_comment_hashtags,
            )

        # ── 5. Persist publish record ─────────────────────────────────────
        _persist_publish_record(
            post=post,
            ig_media_id=ig_media_id,
            comment_id=comment_id,
            published_at=published_at,
            permalink=permalink,
        )

        logger.info(
            f"Post published successfully | "
            f"ig_media_id={ig_media_id} post_id={post.post_id}"
        )

        return {
            "status":            "ok",
            "instagram_post_id": ig_media_id,
            "permalink":         permalink,
            "published_at":      published_at,
            "first_comment_id":  comment_id,
            "post_id":           post.post_id,
        }

    except ValidationError as exc:
        logger.error(f"Schema validation failed: {exc.json()}")
        return {"status": "error", "error_type": "validation", "detail": exc.errors()}

    except IGAPIError as exc:
        logger.error(f"Instagram API error: {exc}")
        return {"status": "error", "error_type": "ig_api", "detail": str(exc)}

    except Exception as exc:
        logger.exception("Unhandled error in publisher Lambda")
        return {"status": "error", "error_type": "internal", "detail": str(exc)}


# ─── Custom exceptions ────────────────────────────────────────────────────────

class IGAPIError(Exception):
    """Base exception for Instagram Graph API errors."""

class IGRateLimitError(IGAPIError):
    """HTTP 429 or error code 4/32 — triggers tenacity retry."""

class IGAuthError(IGAPIError):
    """Error code 190 — token invalid or expired."""

class IGContainerError(IGAPIError):
    """Container reached ERROR status during processing."""

class IGTimeoutError(IGAPIError):
    """Container polling exceeded max attempts."""


# ─── Publisher class ──────────────────────────────────────────────────────────

class InstagramPublisher:
    """
    Handles all Instagram Graph API interactions for media publication.

    Supports:
      - IMAGE  (feed post with static image)
      - STORY  (image story)
      - REEL   (short video)
      - CAROUSEL (multi-image feed post)
    """

    def __init__(self, account_id: str, access_token: str) -> None:
        self.account_id   = account_id
        self.access_token = access_token
        self.client       = httpx.Client(timeout=30.0)

    def publish(
        self,
        post: PostOutput,
        post_format: PostFormat,
        asset_url: str | None,
        asset_urls: list[str],
    ) -> tuple[str, str]:
        """
        Orchestrate the full publish flow for the given format.

        Returns:
            (ig_media_id, permalink)
        """
        caption    = self._build_caption(post)

        if post_format == PostFormat.CAROUSEL:
            container_id = self._create_carousel_container(
                caption=caption,
                asset_urls=asset_urls or ([asset_url] if asset_url else []),
            )
        elif post_format == PostFormat.REEL:
            if not asset_url:
                raise ValueError("REEL format requires 'asset_url' (video URL)")
            container_id = self._create_reel_container(
                caption=caption,
                video_url=asset_url,
            )
        else:
            # IMAGE or STORY
            if not asset_url:
                raise ValueError(
                    f"{post_format.value.upper()} format requires 'asset_url' (image URL)"
                )
            container_id = self._create_image_container(
                caption=caption,
                image_url=asset_url,
                post_format=post_format,
            )

        # Poll until the container is processed by Instagram
        self._wait_for_container_ready(container_id)

        # Publish
        ig_media_id = self._publish_container(container_id)

        # Fetch permalink
        permalink = self._get_permalink(ig_media_id)

        return ig_media_id, permalink

    # ── Container creation ────────────────────────────────────────────────────

    def _create_image_container(
        self,
        caption: str,
        image_url: str,
        post_format: PostFormat,
    ) -> str:
        """Create a media container for a single IMAGE or STORY post."""
        params: dict = {
            "image_url":    image_url,
            "caption":      caption,
            "access_token": self.access_token,
        }

        if post_format == PostFormat.STORY:
            params["media_type"] = "STORIES"

        response = self._api_post(
            endpoint=f"/{self.account_id}/media",
            params=params,
        )
        container_id = response["id"]
        logger.info(f"Image container created | id={container_id}")
        return container_id

    def _create_reel_container(self, caption: str, video_url: str) -> str:
        """Create a media container for a REEL (short video)."""
        response = self._api_post(
            endpoint=f"/{self.account_id}/media",
            params={
                "media_type":   "REELS",
                "video_url":    video_url,
                "caption":      caption,
                "share_to_feed": "true",
                "access_token": self.access_token,
            },
        )
        container_id = response["id"]
        logger.info(f"Reel container created | id={container_id}")
        return container_id

    def _create_carousel_container(
        self,
        caption: str,
        asset_urls: list[str],
    ) -> str:
        """
        Create a CAROUSEL container.
        Instagram requires creating individual child containers first,
        then wrapping them in a parent carousel container.
        """
        if not asset_urls:
            raise ValueError("Carousel requires at least 2 asset_urls")
        if len(asset_urls) > 10:
            logger.warning(
                f"Carousel has {len(asset_urls)} items — Instagram max is 10. Truncating."
            )
            asset_urls = asset_urls[:10]

        # Step 1: Create a child container for each image
        child_ids: list[str] = []
        for idx, url in enumerate(asset_urls):
            child_resp = self._api_post(
                endpoint=f"/{self.account_id}/media",
                params={
                    "image_url":         url,
                    "is_carousel_item":  "true",
                    "access_token":      self.access_token,
                },
            )
            child_id = child_resp["id"]
            child_ids.append(child_id)
            logger.info(f"Carousel child {idx+1}/{len(asset_urls)} created | id={child_id}")

        # Step 2: Create the parent carousel container
        response = self._api_post(
            endpoint=f"/{self.account_id}/media",
            params={
                "media_type":   "CAROUSEL",
                "children":     ",".join(child_ids),
                "caption":      caption,
                "access_token": self.access_token,
            },
        )
        container_id = response["id"]
        logger.info(
            f"Carousel container created | id={container_id} children={len(child_ids)}"
        )
        return container_id

    # ── Polling ───────────────────────────────────────────────────────────────

    def _wait_for_container_ready(self, container_id: str) -> None:
        """
        Poll the container status endpoint until Instagram reports FINISHED.
        Instagram processes media asynchronously — especially videos/reels.

        Raises:
            IGContainerError: if container reaches ERROR status.
            IGTimeoutError: if max poll attempts are exceeded.
        """
        logger.info(f"Polling container status | id={container_id}")

        for attempt in range(1, POLL_MAX_ATTEMPTS + 1):
            response = self._api_get(
                endpoint=f"/{container_id}",
                params={
                    "fields":       "status_code,status",
                    "access_token": self.access_token,
                },
            )

            status_code = response.get("status_code", "")
            logger.debug(
                f"Container poll attempt {attempt}/{POLL_MAX_ATTEMPTS} "
                f"| status={status_code}"
            )

            if status_code == CONTAINER_FINISHED:
                logger.info(f"Container ready | id={container_id} attempts={attempt}")
                return

            if status_code == CONTAINER_ERROR:
                status_detail = response.get("status", "unknown error")
                raise IGContainerError(
                    f"Container {container_id} processing failed: {status_detail}"
                )

            # Status is IN_PROGRESS or PUBLISHED — keep polling
            time.sleep(POLL_INTERVAL_SEC)

        raise IGTimeoutError(
            f"Container {container_id} did not reach FINISHED after "
            f"{POLL_MAX_ATTEMPTS * POLL_INTERVAL_SEC}s"
        )

    # ── Publishing ────────────────────────────────────────────────────────────

    def _publish_container(self, container_id: str) -> str:
        """Publish a FINISHED container and return the resulting ig_media_id."""
        response = self._api_post(
            endpoint=f"/{self.account_id}/media_publish",
            params={
                "creation_id":  container_id,
                "access_token": self.access_token,
            },
        )
        ig_media_id = response["id"]
        logger.info(f"Container published | ig_media_id={ig_media_id}")
        return ig_media_id

    # ── First comment ─────────────────────────────────────────────────────────

    def post_first_comment(
        self,
        media_id: str,
        hashtags: list[str],
    ) -> str | None:
        """
        Post overflow hashtags as the first comment on the published media.
        Instagram best practice: keep caption hashtags ≤ 5; put the rest here.

        Returns:
            comment_id if successful, None if posting is not applicable.
        """
        if not hashtags:
            return None

        # Normalize hashtags
        normalized = [
            tag if tag.startswith("#") else f"#{tag}"
            for tag in hashtags
        ]
        message = " ".join(normalized)

        # Brief pause — Instagram sometimes rejects immediate comments
        time.sleep(2)

        try:
            response = self._api_post(
                endpoint=f"/{media_id}/comments",
                params={
                    "message":      message,
                    "access_token": self.access_token,
                },
            )
            comment_id = response["id"]
            logger.info(
                f"First comment posted | media_id={media_id} "
                f"hashtags={len(hashtags)} comment_id={comment_id}"
            )
            return comment_id

        except IGAPIError as exc:
            # Non-fatal — log and continue; post is already published
            logger.warning(f"First comment failed (non-fatal): {exc}")
            return None

    # ── Permalink ─────────────────────────────────────────────────────────────

    def _get_permalink(self, media_id: str) -> str:
        """Fetch the public permalink of a published media object."""
        try:
            response = self._api_get(
                endpoint=f"/{media_id}",
                params={
                    "fields":       "permalink",
                    "access_token": self.access_token,
                },
            )
            return response.get("permalink", "")
        except IGAPIError:
            logger.warning("Could not retrieve permalink — returning empty string")
            return ""

    # ── Caption assembly ─────────────────────────────────────────────────────

    @staticmethod
    def _build_caption(post: PostOutput) -> str:
        """
        Combine caption body + in-caption hashtags into the final caption string.
        Enforces the 2,200 character hard limit.
        """
        hashtag_block = " ".join(
            tag if tag.startswith("#") else f"#{tag}"
            for tag in post.hashtags
        )
        full_caption = (
            f"{post.caption}\n\n{hashtag_block}".strip()
            if hashtag_block
            else post.caption.strip()
        )

        if len(full_caption) > 2200:
            logger.warning(
                f"Caption + hashtags = {len(full_caption)} chars — "
                "trimming to 2200 limit"
            )
            full_caption = full_caption[:2200]

        return full_caption

    @staticmethod
    def _resolve_media_type(post_format: PostFormat) -> str:
        mapping = {
            PostFormat.FEED:     "IMAGE",
            PostFormat.STORY:    "STORIES",
            PostFormat.REEL:     "REELS",
            PostFormat.CAROUSEL: "CAROUSEL",
        }
        return mapping[post_format]

    # ── HTTP layer ────────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(IGRateLimitError),
        wait=wait_exponential(multiplier=2, min=10, max=120),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _api_post(self, endpoint: str, params: dict) -> dict:
        """POST to the Graph API with retry on rate-limit (HTTP 429)."""
        url = f"{GRAPH_API_BASE}{endpoint}"
        logger.debug(f"POST {url} | params_keys={list(params.keys())}")

        resp = self.client.post(url, data=params)
        return self._handle_response(resp)

    @retry(
        retry=retry_if_exception_type(IGRateLimitError),
        wait=wait_exponential(multiplier=2, min=10, max=60),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _api_get(self, endpoint: str, params: dict) -> dict:
        """GET from the Graph API with retry on rate-limit."""
        url = f"{GRAPH_API_BASE}{endpoint}"
        resp = self.client.get(url, params=params)
        return self._handle_response(resp)

    @staticmethod
    def _handle_response(resp: httpx.Response) -> dict:
        """
        Parse Graph API response and raise typed errors on failure.

        Instagram error codes of interest:
          4     : Application request limit reached (rate limit)
          190   : Access token invalid or expired
          100   : Invalid parameter
          10    : Permission denied
          32    : Page/app request limit
        """
        try:
            data = resp.json()
        except Exception:
            raise IGAPIError(f"Non-JSON response: {resp.status_code} — {resp.text[:200]}")

        if "error" in data:
            err     = data["error"]
            code    = err.get("code", 0)
            subcode = err.get("error_subcode", 0)
            message = err.get("message", "Unknown IG error")

            if code == 4 or code == 32 or resp.status_code == 429:
                raise IGRateLimitError(f"IG rate limit hit (code={code}): {message}")

            if code == 190:
                raise IGAuthError(f"IG access token invalid/expired: {message}")

            raise IGAPIError(f"IG API error (code={code} sub={subcode}): {message}")

        return data


# ─── Access token loading ─────────────────────────────────────────────────────

def _load_access_token(account_id: str) -> str:
    """
    Load the long-lived Instagram access token from Secrets Manager.
    Token is cached in-memory across warm Lambda invocations.

    Secret structure (JSON string):
        { "access_token": "EAABsbCS..." }

    Token rotation:
        Instagram long-lived tokens expire after 60 days.
        A separate scheduled Lambda should refresh them and update the secret.
        See: https://developers.facebook.com/docs/instagram-basic-display-api/guides/long-lived-access-tokens
    """
    cache_key = f"{SECRET_NAME}:{account_id}"
    if cache_key in _token_cache:
        return _token_cache[cache_key]

    try:
        response = secrets_client.get_secret_value(SecretId=SECRET_NAME)
        secret   = json.loads(response["SecretString"])
        token    = secret.get("access_token") or secret.get(account_id)

        if not token:
            raise IGAuthError(
                f"Secret '{SECRET_NAME}' does not contain 'access_token' "
                f"or key '{account_id}'"
            )

        _token_cache[cache_key] = token
        logger.info("IG access token loaded from Secrets Manager")
        return token

    except secrets_client.exceptions.ResourceNotFoundException:
        raise IGAuthError(f"Secret '{SECRET_NAME}' not found in Secrets Manager")
    except json.JSONDecodeError as exc:
        raise IGAuthError(f"Secret '{SECRET_NAME}' is not valid JSON: {exc}")


# ─── DynamoDB persistence ─────────────────────────────────────────────────────

def _persist_publish_record(
    post: PostOutput,
    ig_media_id: str,
    comment_id: str | None,
    published_at: str,
    permalink: str,
) -> None:
    """
    Write a publish audit record to DynamoDB.
    This table drives the metrics feedback loop back to the Vector Store.

    Schema:
        PK: post_id (S)
        SK: published_at (S)
        Attributes: ig_media_id, brief_id, trend_id, permalink,
                    first_comment_id, hashtags, caption_length, ttl
    """
    try:
        table = dynamodb.Table(PUBLISH_TABLE)

        # TTL: 90 days from now (for automatic cleanup)
        ttl = int(time.time()) + (90 * 24 * 3600)

        table.put_item(
            Item={
                "post_id":          post.post_id,
                "published_at":     published_at,
                "ig_media_id":      ig_media_id,
                "brief_id":         post.brief_id,
                "trend_id":         post.trend_id,
                "permalink":        permalink,
                "first_comment_id": comment_id or "",
                "hashtags":         post.hashtags,
                "first_comment_hashtags": post.first_comment_hashtags,
                "caption_length":   len(post.caption),
                "cta":              post.cta,
                "visual_style":     post.visual_brief.visual_style,
                "ttl":              ttl,
                # Metrics fields — populated later by a separate engagement Lambda
                "likes":            0,
                "comments":         0,
                "shares":           0,
                "reach":            0,
                "metrics_updated_at": "",
            }
        )
        logger.info(f"Publish record persisted | post_id={post.post_id}")

    except Exception as exc:
        # Non-fatal — the post is already live; don't fail the pipeline over this
        logger.warning(f"DynamoDB persist failed (non-fatal): {exc}")
