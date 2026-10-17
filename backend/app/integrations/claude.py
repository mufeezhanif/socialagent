"""Thin wrapper over the Anthropic SDK: structured outputs only, never raises into the pipeline."""

import base64
import logging
from pathlib import Path
from typing import TypeVar

import anthropic
from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_client: AsyncAnthropic | None = None


def enabled() -> bool:
    return bool(settings.anthropic_api_key)


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=3, timeout=180.0)
    return _client


def image_block(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


async def parse(
    schema: type[T],
    *,
    system: str,
    content: str | list,
    effort: str = "low",
    max_tokens: int = 8000,
    usage: dict | None = None,
) -> T | None:
    """Ask Claude for a structured result. Returns None on any failure so callers can fall back. Token counts are
    added to `usage` when given."""
    if not enabled():
        return None
    try:
        response = await _get_client().beta.messages.parse(
            model=settings.claude_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=schema,
            output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError as exc:
        log.warning("claude rate limited: %s", exc)
        return None
    except anthropic.APIStatusError as exc:
        log.warning("claude API error %s: %s", exc.status_code, exc.message)
        return None
    except anthropic.APIConnectionError as exc:
        log.warning("claude connection error: %s", exc)
        return None
    except ValidationError as exc:
        log.warning("claude output failed validation: %s", exc)
        return None
    if usage is not None:
        u = response.usage
        usage["calls"] = usage.get("calls", 0) + 1
        usage["input"] = usage.get("input", 0) + u.input_tokens + (u.cache_read_input_tokens or 0) + (
            u.cache_creation_input_tokens or 0)
        usage["output"] = usage.get("output", 0) + u.output_tokens
    if response.stop_reason == "refusal":
        log.warning("claude refused (%s)", getattr(response, "stop_details", None))
        return None
    if response.stop_reason == "max_tokens":
        log.warning("claude hit max_tokens for %s", schema.__name__)
        return None
    return response.parsed_output
