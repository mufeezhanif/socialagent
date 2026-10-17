"""Facebook Pages via Facebook Login: OAuth, Page tokens and Reels publishing."""

import asyncio
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app.config import settings

SCOPES = "pages_show_list,pages_read_engagement,pages_manage_posts"


class FacebookError(RuntimeError):
    pass


def configured() -> bool:
    return bool(settings.fb_app_id and settings.fb_app_secret)


def _graph(path: str) -> str:
    return f"https://graph.facebook.com/{settings.fb_graph_version.strip('/')}/{path.lstrip('/')}"


def _raise_for(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400 or (isinstance(data, dict) and "error" in data):
        err = data.get("error") if isinstance(data.get("error"), dict) else {}
        raise FacebookError(str(err.get("error_user_msg") or err.get("message") or response.text[:300]))
    return data


def authorize_url(state: str) -> str:
    query = {
        "client_id": settings.fb_app_id,
        "redirect_uri": settings.facebook_redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if settings.fb_login_config_id:
        query["config_id"] = settings.fb_login_config_id
    else:
        query["scope"] = SCOPES
    return f"https://www.facebook.com/{settings.fb_graph_version.strip('/')}/dialog/oauth?{urlencode(query)}"


async def exchange_code(code: str) -> str:
    """Authorization code -> short-lived user token -> long-lived user token (Page tokens from it don't expire)."""
    async with httpx.AsyncClient(timeout=30) as client:
        short = _raise_for(
            await client.get(
                _graph("oauth/access_token"),
                params={
                    "client_id": settings.fb_app_id,
                    "client_secret": settings.fb_app_secret,
                    "redirect_uri": settings.facebook_redirect_uri,
                    "code": code,
                },
            )
        )
        long = _raise_for(
            await client.get(
                _graph("oauth/access_token"),
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.fb_app_id,
                    "client_secret": settings.fb_app_secret,
                    "fb_exchange_token": short["access_token"],
                },
            )
        )
    return long["access_token"]


async def pages(user_token: str) -> list[dict]:
    """Pages this person manages, each with its own Page access token."""
    async with httpx.AsyncClient(timeout=30) as client:
        data = _raise_for(
            await client.get(
                _graph("me/accounts"),
                params={"fields": "id,name,access_token,picture{url}", "limit": 50, "access_token": user_token},
            )
        )
    return [p for p in data.get("data", []) if p.get("access_token")]


async def page_info(page_id: str, page_token: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        return _raise_for(
            await client.get(_graph(page_id), params={"fields": "id,name,followers_count", "access_token": page_token})
        )


async def publish_reel(page_id: str, page_token: str, video_path: str | Path, description: str) -> tuple[str, str]:
    """Start a Reel upload -> send the file bytes -> publish -> wait until Facebook has processed it.

    Uploads the bytes directly, so it also works when the app isn't reachable from the internet.
    Returns (video_id, permalink).
    """
    body = Path(video_path).read_bytes()
    async with httpx.AsyncClient(timeout=180) as client:
        start = _raise_for(
            await client.post(_graph(f"{page_id}/video_reels"), data={"upload_phase": "start", "access_token": page_token})
        )
        video_id = start["video_id"]
        upload_url = start.get("upload_url") or (
            f"https://rupload.facebook.com/video-upload/{settings.fb_graph_version.strip('/')}/{video_id}"
        )
        uploaded = _raise_for(
            await client.post(
                upload_url,
                headers={"Authorization": f"OAuth {page_token}", "offset": "0", "file_size": str(len(body))},
                content=body,
            )
        )
        if not uploaded.get("success", True):
            raise FacebookError("Facebook did not accept the video upload")
        _raise_for(
            await client.post(
                _graph(f"{page_id}/video_reels"),
                data={
                    "upload_phase": "finish",
                    "video_id": video_id,
                    "video_state": "PUBLISHED",
                    "description": description,
                    "access_token": page_token,
                },
            )
        )

        waited = 0.0
        while waited <= 300:
            await asyncio.sleep(5)
            waited += 5
            info = _raise_for(
                await client.get(_graph(video_id), params={"fields": "status,permalink_url", "access_token": page_token})
            )
            status = info.get("status") or {}
            if status.get("video_status") == "error" or (status.get("processing_phase") or {}).get("status") == "error":
                raise FacebookError("Facebook could not process the video")
            if (status.get("publishing_phase") or {}).get("status") == "complete" or status.get("video_status") == "ready":
                break
        permalink = info.get("permalink_url") or f"/reel/{video_id}"
    if permalink.startswith("/"):
        permalink = f"https://www.facebook.com{permalink}"
    return video_id, permalink
