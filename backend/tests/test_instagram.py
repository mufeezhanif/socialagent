"""Instagram client against a mocked Graph API (request shapes and the polling/publish sequence)."""

import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config import settings
from app.integrations import instagram_api


@pytest.fixture
def mock_graph(monkeypatch):
    calls: list[tuple[str, str]] = []
    state = {"polls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url
        calls.append((request.method, url.path))
        if url.host == "api.instagram.com" and url.path == "/oauth/access_token":
            body = request.content.decode(errors="ignore")
            assert "authorization_code" in body and "the-code" in body and "#_" not in body
            return httpx.Response(200, json={"data": [{"access_token": "short", "user_id": "17", "permissions": "x"}]})
        if url.path == "/access_token":
            assert url.params["grant_type"] == "ig_exchange_token" and url.params["access_token"] == "short"
            return httpx.Response(200, json={"access_token": "long", "token_type": "bearer", "expires_in": 5183944})
        if url.path.endswith("/me"):
            return httpx.Response(200, json={"user_id": "1789", "username": "demo.creator", "account_type": "MEDIA_CREATOR"})
        if url.path.endswith("/1789/media") and request.method == "POST":
            form = parse_qs(request.content.decode())
            assert form["media_type"] == ["REELS"] and form["share_to_feed"] == ["true"]
            assert form["video_url"][0].startswith("https://")
            return httpx.Response(200, json={"id": "C1"})
        if url.path.endswith("/C1"):
            state["polls"] += 1
            code = "IN_PROGRESS" if state["polls"] < 3 else "FINISHED"
            return httpx.Response(200, json={"status_code": code, "id": "C1"})
        if url.path.endswith("/1789/media_publish"):
            assert parse_qs(request.content.decode())["creation_id"] == ["C1"]
            return httpx.Response(200, json={"id": "M1"})
        if url.path.endswith("/M1"):
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/reel/abc/"})
        if url.path.endswith("/1789/content_publishing_limit"):
            return httpx.Response(200, json={"data": [{"quota_usage": 2, "config": {"quota_total": 100}}]})
        return httpx.Response(404, json={"error": {"message": f"unexpected {url}"}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(instagram_api.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))

    async def no_sleep(_):
        return None

    monkeypatch.setattr(instagram_api.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(settings, "ig_app_id", "123")
    monkeypatch.setattr(settings, "ig_app_secret", "s3cret")
    return calls, state


def test_authorize_url_has_required_params(monkeypatch):
    monkeypatch.setattr(settings, "ig_app_id", "123")
    q = parse_qs(urlparse(instagram_api.authorize_url("st")).query)
    assert q["client_id"] == ["123"] and q["response_type"] == ["code"] and q["state"] == ["st"]
    assert set(q["scope"][0].split(",")) == {"instagram_business_basic", "instagram_business_content_publish"}
    assert q["redirect_uri"][0].endswith("/api/instagram/callback")


def test_oauth_exchange_and_profile(mock_graph):
    token, expires = asyncio.run(instagram_api.exchange_code("the-code#_"))
    assert token == "long" and expires.year >= 2026
    profile = asyncio.run(instagram_api.me(token))
    assert profile["account_type"] in instagram_api.PROFESSIONAL_TYPES


def test_publish_polls_until_finished_then_publishes(mock_graph):
    calls, state = mock_graph
    seen = []

    async def remember(container):
        seen.append(container)

    media_id, permalink = asyncio.run(instagram_api.publish_reel(
        "1789", "long", "https://example.com/media/x.mp4", "caption #tag", on_container=remember))
    assert (media_id, permalink, seen) == ("M1", "https://www.instagram.com/reel/abc/", ["C1"])
    assert state["polls"] == 3
    assert [p for m, p in calls if m == "POST"][-1].endswith("/media_publish")
    assert all("/v25.0/" in p for m, p in calls if "graph" in p or p.endswith(("/media", "/media_publish")))


def test_quota_and_errors(mock_graph):
    assert asyncio.run(instagram_api.publishing_limit("1789", "long")) == {"quota_usage": 2, "quota_total": 100}
    with pytest.raises(instagram_api.InstagramError):
        asyncio.run(instagram_api.publish_reel("999", "long", "https://x/y.mp4", "c"))
