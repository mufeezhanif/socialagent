import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import db, mcp_server
from app.agent import engine
from app.db import get_session
from app.deps import current_user
from app.models import ApiToken, AuditEvent, Draft, DraftStatus as S, User
from app.routes import tokens

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    """Isolated SQLite DB; every module that imported SessionLocal by name is pointed at it."""
    eng = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 't.db').as_posix()}")
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with eng.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    for mod in (db, mcp_server, engine):
        monkeypatch.setattr(mod, "SessionLocal", maker)
    async with maker() as s:
        alice = User(email="a@x.com", password_hash="x")
        bob = User(email="b@x.com", password_hash="x")
        s.add_all([alice, bob])
        await s.flush()
        mine = Draft(user_id=alice.id, status=S.AWAITING_VIDEO_APPROVAL)
        theirs = Draft(user_id=bob.id, status=S.AWAITING_VIDEO_APPROVAL, caption_final="secret")
        s.add_all([mine, theirs])
        await s.commit()
    yield {"maker": maker, "alice": alice.id, "bob": bob.id, "mine": mine.id, "theirs": theirs.id}
    await eng.dispose()


def token_app(maker) -> FastAPI:
    app = FastAPI()
    app.include_router(tokens.router)

    async def session():
        async with maker() as s:
            yield s

    async def user(request: Request):  # test stand-in for the cookie login: header names the user
        async with maker() as s:
            return await s.get(User, request.headers["x-user"])

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[current_user] = user
    return app


async def test_token_create_list_revoke_scoped(env):
    app = token_app(env["maker"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        a, b = {"x-user": env["alice"]}, {"x-user": env["bob"]}
        made = (await c.post("/api/mcp/tokens", json={"name": "Claude"}, headers=a)).json()
        assert made["token"].startswith("sa_") and made["prefix"] == made["token"][:10]
        listed = (await c.get("/api/mcp/tokens", headers=a)).json()
        assert [t["id"] for t in listed] == [made["id"]] and "token" not in listed[0] and "token_hash" not in listed[0]
        assert (await c.get("/api/mcp/tokens", headers=b)).json() == []
        assert (await c.delete(f"/api/mcp/tokens/{made['id']}", headers=b)).status_code == 404
        assert (await c.delete(f"/api/mcp/tokens/{made['id']}", headers=a)).status_code == 200
        assert (await c.get("/api/mcp/tokens", headers=a)).json() == []
    async with env["maker"]() as s:
        assert await s.scalar(select(ApiToken)) is None


async def test_token_limit_and_hash_only(env):
    app = token_app(env["maker"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        a = {"x-user": env["alice"]}
        made = [(await c.post("/api/mcp/tokens", json={}, headers=a)) for _ in range(6)]
        assert [r.status_code for r in made] == [200] * 5 + [400]
    async with env["maker"]() as s:
        row = await s.scalar(select(ApiToken))
        assert row.token_hash == tokens.hash_token(made[0].json()["token"]) and "sa_" not in row.token_hash


async def call_through_auth(header: str | None):
    seen = {}

    async def inner(scope, receive, send):
        seen["uid"] = mcp_server.current_user_id.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = mcp_server.BearerAuth(inner)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/", headers={"authorization": header} if header else {})
    return r, seen


async def test_auth_rejects_missing_and_bad_tokens(env):
    for header in (None, "Bearer", "Bearer sa_nope", "Basic abc", "Bearer notmine"):
        r, seen = await call_through_auth(header)
        assert r.status_code == 401 and "error" in r.json() and "uid" not in seen


async def test_auth_accepts_valid_token_and_sets_user(env):
    plain = "sa_" + "k" * 43
    async with env["maker"]() as s:
        s.add(ApiToken(user_id=env["alice"], token_hash=tokens.hash_token(plain), prefix=plain[:10]))
        await s.commit()
    r, seen = await call_through_auth(f"Bearer {plain}")
    assert r.status_code == 200 and seen["uid"] == env["alice"]
    assert mcp_server.current_user_id.get() is None  # reset after the request
    async with env["maker"]() as s:
        assert (await s.scalar(select(ApiToken))).last_used_at is not None


async def test_tools_refuse_other_users_drafts(env, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("engine must not run for someone else's draft")

    monkeypatch.setattr(engine, "run_action", boom)
    mcp_server.current_user_id.set(env["alice"])
    theirs = env["theirs"]
    for call in (
        mcp_server.get_draft(theirs),
        mcp_server.request_changes(theirs, "cut it"),
        mcp_server.choose_caption(theirs, 1),
        mcp_server.request_publish(theirs),
    ):
        with pytest.raises(ValueError, match="not found"):
            await call
    listed = await mcp_server.list_drafts()
    assert [d["id"] for d in listed] == [env["mine"]]


async def test_get_draft_and_audit(env):
    mcp_server.current_user_id.set(env["alice"])
    out = await mcp_server.get_draft(env["mine"])
    assert out["id"] == env["mine"] and out["status"] == S.AWAITING_VIDEO_APPROVAL
    async with env["maker"]() as s:
        ev = await s.scalar(select(AuditEvent).where(AuditEvent.draft_id == env["mine"]))
        assert (ev.actor, ev.action, ev.detail) == ("ai", "assistant_request", {"tool": "get_draft", "via": "mcp"})


async def test_request_publish_only_asks_never_posts(env, monkeypatch):
    mcp_server.current_user_id.set(env["alice"])
    with pytest.raises(ValueError, match="caption"):
        await mcp_server.request_publish(env["mine"])
    async with env["maker"]() as s:
        d = await s.get(Draft, env["mine"])
        d.caption_final, d.status = "hello", S.SAVED
        await s.commit()
    calls = []

    async def fake_ask(ctx, draft, prefix=""):
        calls.append("ask")

    async def never(*a, **k):
        raise AssertionError("must not publish")

    monkeypatch.setattr(engine, "ask_publish", fake_ask)
    monkeypatch.setattr(engine, "publish_now", never)
    monkeypatch.setattr(engine, "schedule_at", never)
    out = await mcp_server.request_publish(env["mine"])
    assert calls == ["ask"] and "Nothing is posted" in out["message"]


async def test_request_changes_state_rule(env):
    mcp_server.current_user_id.set(env["alice"])
    async with env["maker"]() as s:
        d = await s.get(Draft, env["mine"])
        d.status = S.PUBLISHED
        await s.commit()
    with pytest.raises(ValueError, match="Not possible"):
        await mcp_server.request_changes(env["mine"], "cut the intro")


async def test_update_brand_kit_validates(env):
    mcp_server.current_user_id.set(env["alice"])
    with pytest.raises(ValueError):
        await mcp_server.update_brand_kit({"primary_color": "red"})
    with pytest.raises(ValueError, match="Unknown fields"):
        await mcp_server.update_brand_kit({"nope": 1})
    out = await mcp_server.update_brand_kit({"tone": "playful"})
    assert out["tone"] == "playful" and (await mcp_server.get_brand_kit())["tone"] == "playful"
