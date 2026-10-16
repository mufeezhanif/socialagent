"""Provider-agnostic LLM access: Gemini and Groq through their OpenAI-compatible endpoints, Claude as a further
fallback, and None when nothing is configured so callers can use deterministic logic."""

import asyncio
import base64
import copy
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.integrations import claude

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str
    max_images: int  # images the main model accepts per request (0 = text only)
    vision_model: str | None = None  # separate model used only to describe frames
    vision_max_images: int = 0
    extra: dict = field(default_factory=dict)


def providers() -> list[Provider]:
    """OpenAI-compatible providers that have keys, in the configured order."""
    available = {
        "gemini": Provider(
            name="gemini",
            base_url=settings.gemini_base_url.rstrip("/"),
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            max_images=8,
        ) if settings.gemini_api_key else None,
        "groq": Provider(
            name="groq",
            base_url=settings.groq_base_url.rstrip("/"),
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            max_images=0,
            vision_model=settings.groq_vision_model or None,
            vision_max_images=3,
            extra={"reasoning_effort": "medium"} if settings.groq_model.startswith("openai/gpt-oss") else {},
        ) if settings.groq_api_key else None,
    }
    order = [p.strip().lower() for p in settings.llm_providers.split(",") if p.strip()]
    return [available[name] for name in order if available.get(name)]


def any_configured() -> bool:
    return bool(providers()) or claude.enabled()


def names() -> list[str]:
    out = [p.name for p in providers()]
    if claude.enabled() and "anthropic" in settings.llm_providers:
        out.append("anthropic")
    return out


def image_part(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}


async def chat(
    provider: Provider,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    response_format: dict | None = None,
    model: str | None = None,
    max_tokens: int = 4000,
    use_extra: bool = True,
) -> dict:
    """One chat completion. Returns the assistant message dict (tool_calls included)."""
    payload: dict = {"model": model or provider.model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if response_format:
        payload["response_format"] = response_format
    if use_extra and model in (None, provider.model):
        payload.update(provider.extra)
    headers = {"Authorization": f"Bearer {provider.api_key}"}
    last_error = "unknown error"
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(f"{provider.base_url}/chat/completions", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            last_error = f"{provider.name} connection error: {exc}"
            await asyncio.sleep(1.5 * (attempt + 1))
            continue
        if response.status_code == 429 or response.status_code >= 500:
            last_error = f"{provider.name} {response.status_code}: {response.text[:200]}"
            retry_after = response.headers.get("retry-after")
            await asyncio.sleep(min(float(retry_after), 8) if retry_after and retry_after.replace(".", "").isdigit() else 2 * (attempt + 1))
            continue
        if response.status_code >= 400:
            raise LLMError(f"{provider.name} {response.status_code}: {response.text[:400]}")
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        message["_finish_reason"] = choice.get("finish_reason")
        return message
    raise LLMError(last_error)


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema -> self-contained strict JSON schema (refs inlined, all fields required, no extras)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            node = {k: resolve(v) for k, v in node.items() if k not in ("title", "default")}
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"].keys())
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [resolve(x) for x in node]
        return node

    return resolve(schema)


def extract_json(text: str) -> str:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


async def structured(
    schema: type[T],
    *,
    system: str,
    text: str,
    images: list[Path] | None = None,
    effort: str = "low",
    max_tokens: int = 4000,
) -> T | None:
    """Structured result from the first provider that answers validly; Claude next; None if all fail."""
    images = images or []
    json_schema = strict_schema(schema)
    for provider in providers():
        content: list[dict] = [{"type": "text", "text": text}]
        content += [image_part(p) for p in images[: provider.max_images]]
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        formats = [
            {"type": "json_schema", "json_schema": {"name": schema.__name__, "strict": True, "schema": json_schema}},
            {"type": "json_object"},
        ]
        for fmt in formats:
            msgs = messages
            if fmt["type"] == "json_object":
                msgs = [{"role": "system", "content": system + "\n\nReply with only a JSON object matching this schema:\n"
                         + json.dumps(json_schema)}, messages[1]]
            try:
                reply = await chat(provider, msgs, response_format=fmt, max_tokens=max_tokens)
                return schema.model_validate_json(extract_json(reply.get("content") or ""))
            except (LLMError, ValidationError, ValueError) as exc:
                log.warning("%s structured %s (%s) failed: %s", provider.name, schema.__name__, fmt["type"], str(exc)[:300])
    if "anthropic" in settings.llm_providers:
        from app.integrations.claude import image_block

        blocks: list = [image_block(p) for p in images[:8]] + [{"type": "text", "text": text}]
        return await claude.parse(schema, system=system, content=blocks if images else text, effort=effort, max_tokens=max_tokens)
    return None


async def describe_frames(provider: Provider, frames: list[Path]) -> str:
    """For text-only models: a short visual description from the provider's vision model."""
    if not provider.vision_model or not frames:
        return ""
    picks = [frames[int(i * (len(frames) - 1) / max(provider.vision_max_images - 1, 1))]
             for i in range(min(provider.vision_max_images, len(frames)))]
    content = [{"type": "text", "text": "These are frames from one short video, in order. In 2-4 sentences describe "
                "what the video shows: people, setting, products, on-screen text, and where the main subject sits in "
                "the frame (left/centre/right)."}] + [image_part(p) for p in picks]
    try:
        reply = await chat(provider, [{"role": "user", "content": content}], model=provider.vision_model,
                           max_tokens=600, use_extra=False)
        return (reply.get("content") or "").strip()[:800]
    except LLMError as exc:
        log.warning("frame description failed: %s", exc)
        return ""
