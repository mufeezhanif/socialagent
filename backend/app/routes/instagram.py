import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps import current_user
from app.integrations import instagram_api
from app.models import InstagramAccount, User, utcnow
from app.security import create_state_token, decrypt_text, encrypt_text, read_state_token
from app.services.audit import audit

router = APIRouter(prefix="/api/instagram", tags=["instagram"])
log = logging.getLogger(__name__)


def _back(result: str, reason: str = "") -> RedirectResponse:
    url = f"{settings.frontend_url.rstrip('/')}/onboarding?ig={result}"
    if reason:
        url += f"&reason={quote(reason[:200])}"
    return RedirectResponse(url, status_code=302)


@router.get("/connect")
async def connect(user: User = Depends(current_user)):
    if not instagram_api.configured():
        raise HTTPException(503, "Instagram isn't set up on the server yet (IG_APP_ID / IG_APP_SECRET missing)")
    return {"url": instagram_api.authorize_url(create_state_token(user.id, "ig")),
            "redirect_uri": settings.instagram_redirect_uri}


@router.get("/callback")
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    if error or not code:
        return _back("error", error_description or error or "cancelled")
    user_id = read_state_token(state or "", "ig")
    if not user_id or not await session.get(User, user_id):
        return _back("error", "session expired, please try again")
    try:
        token, expires = await instagram_api.exchange_code(code)
        profile = await instagram_api.me(token)
    except instagram_api.InstagramError as exc:
        log.warning("instagram connect failed: %s", exc)
        return _back("error", str(exc))
    account_type = (profile.get("account_type") or "").upper()
    if account_type and account_type not in instagram_api.PROFESSIONAL_TYPES:
        return _back("error", "Switch the Instagram account to Professional (Creator or Business), then connect again")

    account = await session.scalar(select(InstagramAccount).where(InstagramAccount.user_id == user_id))
    if account is None:
        account = InstagramAccount(user_id=user_id, access_token_enc="")
        session.add(account)
    account.ig_user_id = str(profile.get("user_id") or profile.get("id"))
    account.username = profile.get("username", "")
    account.account_type = account_type
    account.profile_picture_url = profile.get("profile_picture_url", "")
    account.access_token_enc = encrypt_text(token)
    account.token_expires_at = expires
    account.status = "ok"
    account.connected_at = utcnow()
    audit(session, user_id, None, "human", "connected_instagram", username=account.username)
    await session.commit()
    return _back("connected")


@router.get("/status")
async def status(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Live check: token works, account is professional, and how much of the daily posting quota is left."""
    account = await session.scalar(select(InstagramAccount).where(InstagramAccount.user_id == user.id))
    if account is None:
        return {"connected": False, "configured": instagram_api.configured()}
    token = decrypt_text(account.access_token_enc)
    out = {
        "connected": True,
        "configured": instagram_api.configured(),
        "username": account.username,
        "account_type": account.account_type,
        "token_expires_at": account.token_expires_at.isoformat() if account.token_expires_at else None,
    }
    if not token:
        return {**out, "ok": False, "error": "Stored token can't be read; reconnect Instagram"}
    try:
        profile = await instagram_api.me(token)
        quota = await instagram_api.publishing_limit(account.ig_user_id, token)
    except instagram_api.InstagramError as exc:
        account.status = "error"
        await session.commit()
        return {**out, "ok": False, "error": str(exc)}
    account.status, account.username = "ok", profile.get("username", account.username)
    await session.commit()
    return {**out, "ok": True, "followers": profile.get("followers_count"), "media_count": profile.get("media_count"),
            **quota}


@router.delete("")
async def disconnect(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    account = await session.scalar(select(InstagramAccount).where(InstagramAccount.user_id == user.id))
    if account:
        await session.delete(account)
        await session.commit()
    return {"ok": True}
