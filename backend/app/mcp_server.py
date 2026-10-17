"""Remote MCP server: lets an AI assistant work on a creator's drafts. It can ask, never publish; the creator approves."""

import contextvars
import hmac
import json
from typing import Any

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select

from app.agent import copy, engine
from app.db import SessionLocal
from app.models import ApiToken, AuditEvent, Draft, DraftStatus as S, User, utcnow
from app.routes import brand as brand_routes
from app.routes.drafts import CAPTION_STATES, _url
from app.routes.tokens import hash_token
from app.services.audit import audit

current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_user_id", default=None)

REVIEW_STATES = {S.AWAITING_VIDEO_APPROVAL, S.AWAITING_CHANGE_NOTES}
ASK_STATES = {S.AWAITING_PUBLISH_CHOICE, S.AWAITING_SCHEDULE_TIME, S.SAVED}

mcp = FastMCP(
    "SocialAgent",
    instructions=(
        "Work on the creator's Instagram Reel drafts. You can review, request edits, pick captions and ask to publish. "
        "Nothing is ever posted from here: request_publish sends the question to the creator, who decides."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    # Bearer tokens guard this endpoint; the default localhost-only Host allowlist would reject the real domain.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _uid() -> str:
    uid = current_user_id.get()
    if not uid:
        raise ValueError("Not authenticated")
    return uid


async def _owned(session, draft_id: str) -> Draft:
    draft = await session.get(Draft, draft_id)
    if draft is None or draft.user_id != _uid():
        raise ValueError("Draft not found")
    return draft


async def _log(tool: str, draft_id: str | None = None, **extra: Any) -> None:
    async with SessionLocal() as session:
        audit(session, _uid(), draft_id, "ai", "assistant_request", tool=tool, via="mcp", **extra)
        await session.commit()


def _label(status: str) -> str:
    return copy.STATUS_LABELS.get(status, status)


async def _act(draft_id: str, allowed: set[str], fn, *args) -> None:
    """Run an engine action with the same state rules as the dashboard routes."""

    async def action(ctx, draft):
        if draft.status not in allowed:
            raise ValueError(f"Not possible while the draft is '{_label(draft.status)}'")
        await fn(ctx, draft, *args)

    try:
        await engine.run_action(_uid(), draft_id, action)
    except LookupError:
        raise ValueError("Draft not found")


@mcp.tool()
async def list_drafts(status: str | None = None) -> list[dict]:
    """List your drafts, newest first (max 30). Optional status filter, e.g. awaiting_video_approval, scheduled, published."""
    async with SessionLocal() as session:
        q = select(Draft).where(Draft.user_id == _uid(), Draft.status != S.DISCARDED)
        if status:
            q = q.where(Draft.status == status)
        drafts = (await session.scalars(q.order_by(Draft.created_at.desc()).limit(30))).all()
    await _log("list_drafts")
    return [
        {
            "id": d.id,
            "status": d.status,
            "status_label": _label(d.status),
            "summary": d.edit_summary or [],
            "duration_in": d.duration_in,
            "duration_out": d.duration_out,
            "caption": d.caption_final,
            "created_at": d.created_at.isoformat(),
        }
        for d in drafts
    ]


@mcp.tool()
async def get_draft(draft_id: str) -> dict:
    """Get one draft: status, what the editor did, caption options, chosen caption, schedule, timeline and a preview video link."""
    async with SessionLocal() as session:
        d = await _owned(session, draft_id)
        events = (await session.scalars(select(AuditEvent).where(AuditEvent.draft_id == d.id).order_by(AuditEvent.created_at))).all()
        out = {
            "id": d.id,
            "status": d.status,
            "status_label": _label(d.status),
            "edit_summary": d.edit_summary or [],
            "revision": d.revision,
            "caption_options": (d.caption_pack or {}).get("options", []),
            "caption_final": d.caption_final,
            "hashtags": d.hashtags_final or [],
            "publish_at": d.publish_at.isoformat() if d.publish_at else None,
            "preview_url": _url(d.preview_path),
            "timeline": [{"actor": e.actor, "action": e.action, "detail": e.detail, "at": e.created_at.isoformat()} for e in events],
        }
    await _log("get_draft", draft_id)
    return out


@mcp.tool()
async def request_changes(draft_id: str, notes: str) -> dict:
    """Ask the editor to redo the video with your notes (e.g. 'cut the intro, make captions bigger'). Only while the video awaits review."""
    notes = notes.strip()[:1000]
    if not notes:
        raise ValueError("Say what to change")
    async with SessionLocal() as session:
        await _owned(session, draft_id)
    await _act(draft_id, REVIEW_STATES, engine.request_changes, notes)
    await _log("request_changes", draft_id)
    return {"ok": True, "message": "The editor is revising the video. The creator is notified when it is ready."}


@mcp.tool()
async def choose_caption(draft_id: str, option: int) -> dict:
    """Pick caption option 1, 2 or 3 from get_draft's caption_options."""
    if option not in (1, 2, 3):
        raise ValueError("option must be 1, 2 or 3")
    async with SessionLocal() as session:
        await _owned(session, draft_id)
    await _act(draft_id, CAPTION_STATES, engine.choose_caption, option)
    await _log("choose_caption", draft_id)
    return {"ok": True, "message": f"Caption {option} chosen."}


@mcp.tool()
async def request_publish(draft_id: str) -> dict:
    """Ask the creator to publish. Does NOT post: it sends the creator the 'post now or schedule?' question on WhatsApp or web chat."""
    async with SessionLocal() as session:
        d = await _owned(session, draft_id)
        if not d.caption_final:
            raise ValueError("Choose a caption first")
    await _act(draft_id, ASK_STATES, engine.ask_publish)
    await _log("request_publish", draft_id)
    return {"ok": True, "message": "Sent to the creator for approval on WhatsApp. Nothing is posted until they confirm."}


@mcp.tool()
async def get_brand_kit() -> dict:
    """Get the creator's brand kit: niche, tone, audience, hashtags, banned words, colours, default style, posting time."""
    async with SessionLocal() as session:
        user = await session.get(User, _uid())
        out = await brand_routes.read_brand(user, session)
    await _log("get_brand_kit")
    return out


@mcp.tool()
async def update_brand_kit(fields: dict[str, Any]) -> dict:
    """Change brand kit fields (only the ones you pass), e.g. {"tone": "playful", "default_hashtags": ["bake"]}. Same validation as the dashboard."""
    unknown = set(fields) - set(brand_routes.BrandBody.model_fields)
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    async with SessionLocal() as session:
        user = await session.get(User, _uid())
        current = await brand_routes.read_brand(user, session)
        try:
            body = brand_routes.BrandBody(**{**{k: v for k, v in current.items() if k != "styles"}, **fields})
            out = await brand_routes.update_brand(body, user, session)
        except HTTPException as exc:
            raise ValueError(exc.detail)
        except ValueError as exc:  # pydantic validation
            raise ValueError(str(exc))
    await _log("update_brand_kit", fields=sorted(fields))
    return out


@mcp.tool()
async def get_schedule() -> list[dict]:
    """List upcoming scheduled posts, soonest first."""
    async with SessionLocal() as session:
        rows = (
            await session.scalars(
                select(Draft).where(Draft.user_id == _uid(), Draft.status == S.SCHEDULED).order_by(Draft.publish_at)
            )
        ).all()
    await _log("get_schedule")
    return [{"id": d.id, "publish_at": d.publish_at.isoformat() if d.publish_at else None, "caption": d.caption_final} for d in rows]


class BearerAuth:
    """ASGI wrapper: resolves 'Authorization: Bearer sa_...' to a user and exposes it to the tools via a contextvar."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        user_id = await self.authenticate(dict(scope["headers"]).get(b"authorization", b"").decode("latin-1"))
        if user_id is None:
            body = json.dumps({"error": "Missing or invalid token. Create one under AI assistants in the dashboard."}).encode()
            headers = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b'Bearer realm="socialagent"'),
            ]
            await send({"type": "http.response.start", "status": 401, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return
        reset = current_user_id.set(user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user_id.reset(reset)

    @staticmethod
    async def authenticate(header: str) -> str | None:
        scheme, _, token = header.partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token.startswith("sa_") or len(token) > 200:
            return None
        digest = hash_token(token)
        async with SessionLocal() as session:
            row = await session.scalar(select(ApiToken).where(ApiToken.token_hash == digest))
            if row is None or not hmac.compare_digest(row.token_hash, digest):
                return None
            row.last_used_at = utcnow()
            await session.commit()
            return row.user_id


mcp_app = BearerAuth(mcp.streamable_http_app())


class _ExactPath:
    """ASGI endpoint for the exact path /mcp (no trailing slash), which a Mount alone would not match."""

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            scope = {**scope, "path": "/", "raw_path": b"/"}
        await mcp_app(scope, receive, send)


mcp_root = _ExactPath()
