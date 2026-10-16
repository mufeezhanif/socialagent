"""Instagram API with Instagram Login: OAuth, token refresh, account checks and Reels publishing."""

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import settings

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
SCOPES = "instagram_business_basic,instagram_business_content_publish"
PROFESSIONAL_TYPES = {"BUSINESS", "MEDIA_CREATOR"}


class InstagramError(RuntimeError):
    pass


def configured() -> bool:
    return bool(settings.ig_app_id and settings.ig_app_secret)


def _graph(path: str) -> str:
    version = settings.ig_graph_version.strip("/")
    base = f"https://graph.instagram.com/{version}" if version else "https://graph.instagram.com"
    return f"{base}/{path.lstrip('/')}"


def _raise_for(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400 or (isinstance(data, dict) and "error" in data):
        err = data.get("error") if isinstance(data.get("error"), dict) else {}
        message = (
            err.get("error_user_msg")
            or err.get("message")
            or data.get("error_message")
            or (data.get("error") if isinstance(data.get("error"), str) else None)
            or response.text[:300]
        )
        raise InstagramError(str(message))
    return data


def authorize_url(state: str) -> str:
    query = {
        "client_id": settings.ig_app_id,
        "redirect_uri": settings.instagram_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "enable_fb_login": "false",
        "force_reauth": "true",
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def _expiry(seconds: int | str | None) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=int(seconds or 5_184_000))


async def exchange_code(code: str) -> tuple[str, datetime]:
    """Authorization code -> short-lived token -> long-lived token (about 60 days)."""
    form = {
        "client_id": settings.ig_app_id,
        "client_secret": settings.ig_app_secret,
        "grant_type": "authorization_code",
        "redirect_uri": settings.instagram_redirect_uri,
        "code": code.split("#", 1)[0],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        # Meta documents this endpoint with multipart form fields.
        short = _raise_for(await client.post(TOKEN_URL, files={k: (None, v) for k, v in form.items()}))
        if isinstance(short.get("data"), list) and short["data"]:
            short = short["data"][0]
        if not short.get("access_token"):
            raise InstagramError("Instagram did not return an access token")
        long = _raise_for(
            await client.get(
                "https://graph.instagram.com/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": settings.ig_app_secret,
                    "access_token": short["access_token"],
                },
            )
        )
    return long["access_token"], _expiry(long.get("expires_in"))


async def refresh(token: str) -> tuple[str, datetime]:
    """Extend a long-lived token (allowed once it is at least 24 hours old)."""
    async with httpx.AsyncClient(timeout=30) as client:
        data = _raise_for(
            await client.get(
                "https://graph.instagram.com/refresh_access_token",
                params={"grant_type": "ig_refresh_token", "access_token": token},
            )
        )
    return data["access_token"], _expiry(data.get("expires_in"))


async def me(token: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        return _raise_for(
            await client.get(
                _graph("me"),
                params={
                    "fields": "user_id,username,name,account_type,profile_picture_url,followers_count,media_count",
                    "access_token": token,
                },
            )
        )


async def publishing_limit(ig_user_id: str, token: str) -> dict:
    """{'quota_usage': n, 'quota_total': m} for the rolling 24 h window."""
    async with httpx.AsyncClient(timeout=30) as client:
        data = _raise_for(
            await client.get(
                _graph(f"{ig_user_id}/content_publishing_limit"),
                params={"fields": "config,quota_usage", "access_token": token},
            )
        )
    item = (data.get("data") or [{}])[0]
    return {
        "quota_usage": item.get("quota_usage", 0),
        "quota_total": (item.get("config") or {}).get("quota_total", 100),
    }


async def publish_reel(
    ig_user_id: str, token: str, video_url: str, caption: str, thumb_offset_ms: int = 0, on_container=None
) -> tuple[str, str]:
    """Create a REELS container -> wait until FINISHED -> publish. Returns (media_id, permalink)."""
    async with httpx.AsyncClient(timeout=90) as client:
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

        waited = 0.0
        while True:
            delay = 3 if waited < 30 else 8
            await asyncio.sleep(delay)
            waited += delay
            status = _raise_for(
                await client.get(_graph(container), params={"fields": "status_code,status", "access_token": token})
            )
            code = status.get("status_code")
            if code in {"FINISHED", "PUBLISHED"}:
                break
            if code in {"ERROR", "EXPIRED"}:
                raise InstagramError(status.get("status") or f"Instagram could not process the video ({code})")
            if waited > 300:
                raise InstagramError("Instagram took longer than 5 minutes to process the video")

        media_id = _raise_for(
            await client.post(
                _graph(f"{ig_user_id}/media_publish"), data={"creation_id": container, "access_token": token}
            )
        )["id"]
        permalink = _raise_for(
            await client.get(_graph(media_id), params={"fields": "permalink", "access_token": token})
        ).get("permalink", "")
    return media_id, permalink
