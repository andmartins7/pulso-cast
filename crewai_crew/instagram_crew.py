"""
crewai_crew/instagram_crew.py
─────────────────────────────
InstagramPostCrew: CrewAI crew for Instagram post generation.

Flow:  ContextBrief → [Analyst] → [Copywriter] → [VisualDirector] → PostOutput

Also exposes a Lambda entry-point for Step Functions invocation.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import types
from typing import Any

# Lambda's home dir is read-only; CrewAI's LTMSQLiteStorage tries to mkdir there at import time.
os.environ.setdefault("HOME", "/tmp")

# pkg_resources shim: not bundled in Python 3.12 Lambda base image.
# Provides the subset that crewai uses (get_distribution, require).
if "pkg_resources" not in sys.modules:
    try:
        import pkg_resources  # noqa: F401
    except ImportError:
        import importlib.metadata as _meta
        _m = types.ModuleType("pkg_resources")
        def _get_dist(name):
            try:
                v = _meta.version(name)
            except Exception:
                v = "0.0.0"
            return types.SimpleNamespace(version=v, project_name=name, key=name.lower())
        _m.get_distribution = _get_dist
        _m.require = lambda reqs: []
        _m.DistributionNotFound = Exception
        _m.VersionConflict = Exception
        _m.working_set = types.SimpleNamespace(by_key={}, entries=[])
        sys.modules["pkg_resources"] = _m
        del _m, _get_dist, _meta

from crewai import Crew, Process

from .agents import (
    get_copywriter_agent,
    get_trend_analyst_agent,
    get_visual_director_agent,
)
from crewai_crew.tasks_musicoterapia_hospitalar import (
    get_analyst_task_mt    as get_analyze_trend_task,
    get_copywriter_task_mt as get_write_caption_task,
    get_visual_task_mt     as get_visual_brief_task,
)
from schemas import ContextBrief, PostOutput, VisualBrief

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))


# ─── Crew ─────────────────────────────────────────────────────────────────────

class InstagramPostCrew:
    """
    Orchestrates three specialist CrewAI agents to generate a complete
    Instagram post package from a ContextBrief.

    Usage:
        crew = InstagramPostCrew(context_brief)
        post_output = crew.kickoff()
    """

    def __init__(self, context_brief: ContextBrief) -> None:
        self.brief = context_brief

        # Instantiate agents once (each has its own LLM config)
        self.analyst         = get_trend_analyst_agent()
        self.copywriter      = get_copywriter_agent()
        self.visual_director = get_visual_director_agent()

    # ── Public API ────────────────────────────────────────────────────────────

    def kickoff(self) -> PostOutput:
        """
        Execute the full 3-agent pipeline and return a structured PostOutput.

        Raises:
            ValueError:  if agent output cannot be parsed into PostOutput.
            RuntimeError: if the crew fails after exhausting retries.
        """
        logger.info(
            f"CrewAI kickoff | brief_id={self.brief.brief_id} "
            f"format={self.brief.post_requirements.format.value}"
        )

        crew = self._build_crew()

        try:
            result = crew.kickoff()
        except Exception as exc:
            logger.exception("CrewAI crew execution failed")
            raise RuntimeError(f"Crew execution failed: {exc}") from exc

        raw_output = getattr(result, "raw", None) or str(result)
        logger.info("Crew execution complete — parsing output")

        return self._parse_output(raw_output)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_crew(self) -> Crew:
        """Wire tasks with dependency chain and return a configured Crew."""
        analyze_task = get_analyze_trend_task(self.analyst, self.brief)
        caption_task = get_write_caption_task(self.copywriter, self.brief, analyze_task)
        visual_task  = get_visual_brief_task(self.visual_director, self.brief, caption_task)

        return Crew(
            agents=[self.analyst, self.copywriter, self.visual_director],
            tasks=[analyze_task, caption_task, visual_task],
            process=Process.sequential,
            verbose=True,
            memory=False,   # state managed externally by Step Functions
            max_rpm=10,     # conservative Bedrock rate-limit guard
        )

    def _parse_output(self, raw: str) -> PostOutput:
        """
        Extract structured data from the crew's raw text output.

        Strategy:
          1. Find the caption JSON block (contains key "caption")
          2. Find the visual brief JSON block (contains key "visual_style")
          3. Combine into a validated PostOutput
        """
        caption_data = _extract_json(raw, required_key="caption")
        visual_data  = _extract_json(raw, required_key="visual_style")

        caption_text = caption_data.get("caption", "")
        char_count   = caption_data.get("char_count") or len(caption_text)

        if char_count > 2200:
            logger.warning(
                f"Caption exceeds 2200 chars ({char_count}) — truncating at last sentence boundary"
            )
            caption_text = _truncate_at_sentence(caption_text, 2200)

        return PostOutput(
            brief_id=self.brief.brief_id,
            trend_id=self.brief.trend_id,
            caption=caption_text,
            hashtags=caption_data.get("hashtags_no_caption", []),
            first_comment_hashtags=caption_data.get("hashtags_primeiro_comentario", []),
            cta=caption_data.get("cta", ""),
            visual_brief=VisualBrief(
                primary_color_palette=visual_data.get("primary_color_palette", []),
                visual_style=visual_data.get("visual_style", ""),
                image_prompt=visual_data.get("image_prompt", ""),
                format_specs=visual_data.get("format_specs", {}),
                mood_references=visual_data.get("mood_references", []),
                production_notes=visual_data.get("production_notes", ""),
            ),
        )


# ─── Output parsing utilities ─────────────────────────────────────────────────

def _extract_json(text: str, required_key: str) -> dict:
    """
    Extract the JSON object that contains `required_key` from a text blob.
    Tries three strategies in order:
      1. Pattern match for objects containing the key
      2. All fenced code blocks (```json ... ```)
      3. All top-level braces
    """
    # Strategy 1: targeted pattern
    pattern = r"\{[^{}]*?" + re.escape(required_key) + r"[^{}]*?\}"
    for match in re.finditer(pattern, text, re.DOTALL):
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Strategy 2: fenced code blocks
    for block in re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL):
        try:
            data = json.loads(block.strip())
            if required_key in data:
                return data
        except json.JSONDecodeError:
            pass

    # Strategy 3: all brace pairs (greedy, from last to first)
    blocks = re.findall(r"\{.*?\}", text, re.DOTALL)
    for block in reversed(blocks):
        try:
            data = json.loads(block)
            if required_key in data:
                return data
        except json.JSONDecodeError:
            pass

    logger.warning(f"Could not extract JSON block with key '{required_key}'")
    return {}


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    """Truncate text at the last sentence boundary before max_chars."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_period = max(
        truncated.rfind("."),
        truncated.rfind("!"),
        truncated.rfind("?"),
    )
    return truncated[: last_period + 1] if last_period > 0 else truncated


# ─── Lambda entry-point ───────────────────────────────────────────────────────

def lambda_handler(event: dict, context: Any) -> dict:
    """
    AWS Lambda entry-point.
    Invoked by Step Functions after the Bridge step.

    Event shape:
        { "context_brief": { ...ContextBrief fields... } }

    Returns:
        { "status": "ok", "post_output": { ...PostOutput fields... } }
    """
    raw_brief = event.get("context_brief")
    if not raw_brief:
        return {"status": "error", "detail": "Missing 'context_brief' in event"}

    try:
        brief       = ContextBrief.model_validate(raw_brief)
        crew        = InstagramPostCrew(brief)
        post_output = crew.kickoff()

        return {
            "status":      "ok",
            "post_output": post_output.model_dump(mode="json"),
            "post_id":     post_output.post_id,
        }

    except Exception as exc:
        logger.exception("InstagramPostCrew Lambda failed")
        return {"status": "error", "detail": str(exc)}
