"""HTTP client for the local Baileys gateway (wa-gateway, 127.0.0.1:3001)."""

import httpx

from app.config import settings


class GatewayError(RuntimeError):
    pass


async def _call(method: str, path: str, json: dict | None = None, timeout: float = 60) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                f"{settings.gateway_url}{path}",
                json=json,
                headers={"x-internal-secret": settings.internal_shared_secret},
            )
    except httpx.HTTPError as exc:
        raise GatewayError(f"gateway unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise GatewayError(f"gateway {path} -> {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else {}


async def status() -> dict:
    return await _call("GET", "/status", timeout=10)


async def send_text(jid: str, text: str) -> str | None:
    return (await _call("POST", "/send-text", {"jid": jid, "text": text})).get("id")


async def send_video(jid: str, path: str, caption: str) -> str | None:
    return (await _call("POST", "/send-video", {"jid": jid, "path": path, "caption": caption}, timeout=240)).get("id")


async def typing(jid: str) -> None:
    await _call("POST", "/typing", {"jid": jid}, timeout=10)


async def pair_code(phone: str) -> dict:
    return await _call("POST", "/pair-code", {"phone": phone}, timeout=30)


async def logout() -> dict:
    return await _call("POST", "/logout", {}, timeout=30)


async def set_paused(paused: bool) -> dict:
    return await _call("POST", "/pause", {"paused": paused}, timeout=10)


async def allowlist_add(*jids: str) -> None:
    await _call("POST", "/allowlist/add", {"jids": [j for j in jids if j]}, timeout=10)


async def bot_number() -> str | None:
    """Digits of the bot's WhatsApp number, from the gateway's logged-in identity."""
    try:
        me = (await status()).get("me") or {}
    except GatewayError:
        return None
    raw = me.get("id") or ""
    digits = raw.split("@", 1)[0].split(":", 1)[0]
    return digits if digits.isdigit() else None
