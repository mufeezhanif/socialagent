"""Instagram API with Instagram Login: OAuth + Reels publishing."""

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import settings

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
SCOPES = "instagram_business_basic,instagram_business_content_publish"


class InstagramError(RuntimeError):
    pass


def _graph(path: str) -> str:
    version = settings.ig_graph_version.strip("/")
    base = f"https://graph.instagram.com/{version}" if version else "https://graph.instagram.com"
    return f"{base}/{path.lstrip('/')}"


def _raise_for(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400 or "error" in data:
        err = data.get("error") or {}
        message = err.get("error_user_msg") or err.get("message") or data.get("error_message") or response.text[:300]
        raise InstagramError(message)
    return data


def authorize_url(state: str) -> str:
    query = {
        "client_id": settings.ig_app_id,
        "redirect_uri": settings.instagram_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "enable_fb_login": "0",
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


async def exchange_code(code: str) -> tuple[str, datetime]:
    """Code -> short-lived token -> long-lived token (60 days)."""
    async with httpx.AsyncClient(timeout=30) as client:
        short = _raise_for(
            await client.post(
                TOKEN_URL,
                data={
                    "client_id": settings.ig_app_id,
                    "client_secret": settings.ig_app_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.instagram_redirect_uri,
                    "code": code.removesuffix("#_"),
                },
            )
        )
        if "data" in short and short["data"]:
            short = short["data"][0]
        long = _raise_for(
            await client.get(
                _graph("access_token"),
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": settings.ig_app_secret,
                    "access_token": short["access_token"],
                },
            )
        )
    expires = datetime.now(timezone.utc) + timedelta(seconds=int(long.get("expires_in", 5184000)))
    return long["access_token"], expires


async def me(token: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        return _raise_for(
            await client.get(
                _graph("me"),
                params={"fields": "user_id,username,account_type,profile_picture_url", "access_token": token},
            )
        )


async def publish_reel(
    ig_user_id: str, token: str, video_url: str, caption: str, thumb_offset_ms: int = 0, on_container=None
) -> tuple[str, str]:
    """Create container -> wait until FINISHED -> publish. Returns (media_id, permalink)."""
    async with httpx.AsyncClient(timeout=60) as client:
        container = _raise_for(
            await client.post(
                _graph(f"{ig_user_id}/media"),
                data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption,
                    "share_to_feed": "true",
                    "thumb_offset": str(thumb_offset_ms),
                    "access_token": token,
                },
            )
        )["id"]
        if on_container:
            await on_container(container)

        for _ in range(60):  # up to ~5 minutes
            await asyncio.sleep(5)
            status = _raise_for(
                await client.get(_graph(container), params={"fields": "status_code,status", "access_token": token})
            )
            code = status.get("status_code")
            if code == "FINISHED":
                break
            if code in {"ERROR", "EXPIRED"}:
                raise InstagramError(status.get("status") or f"container {code.lower()}")
        else:
            raise InstagramError("Instagram took too long to process the video")

        media_id = _raise_for(
            await client.post(
                _graph(f"{ig_user_id}/media_publish"), data={"creation_id": container, "access_token": token}
            )
        )["id"]
        permalink = _raise_for(
            await client.get(_graph(media_id), params={"fields": "permalink", "access_token": token})
        ).get("permalink", "")
    return media_id, permalink
