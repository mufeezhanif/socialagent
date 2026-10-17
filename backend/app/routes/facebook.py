import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps import current_user
from app.integrations import facebook_api
from app.models import FacebookPage, User, utcnow
from app.security import create_state_token, decrypt_text, encrypt_text, read_state_token
from app.services.audit import audit

router = APIRouter(prefix="/api/facebook", tags=["facebook"])
log = logging.getLogger(__name__)


def _back(result: str, reason: str = "") -> RedirectResponse:
    url = f"{settings.frontend_url.rstrip('/')}/onboarding?fb={result}"
    if reason:
        url += f"&reason={quote(reason[:200])}"
    return RedirectResponse(url, status_code=302)


@router.get("/connect")
async def connect(user: User = Depends(current_user)):
    if not facebook_api.configured():
        raise HTTPException(503, "Facebook isn't set up on the server yet (FB_APP_ID / FB_APP_SECRET missing)")
    return {"url": facebook_api.authorize_url(create_state_token(user.id, "fb")),
            "redirect_uri": settings.facebook_redirect_uri}


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
    user_id = read_state_token(state or "", "fb")
    if not user_id or not await session.get(User, user_id):
        return _back("error", "session expired, please try again")
    try:
        user_token = await facebook_api.exchange_code(code)
        found = await facebook_api.pages(user_token)
    except facebook_api.FacebookError as exc:
        log.warning("facebook connect failed: %s", exc)
        return _back("error", str(exc))
    if not found:
        return _back("error", "No Facebook Page found. Create a Page (or tick one in the Facebook dialog), then connect again")
    page = found[0]

    account = await session.scalar(select(FacebookPage).where(FacebookPage.user_id == user_id))
    if account is None:
        account = FacebookPage(user_id=user_id, access_token_enc="")
        session.add(account)
    account.page_id = str(page["id"])
    account.name = page.get("name", "")
    account.picture_url = ((page.get("picture") or {}).get("data") or {}).get("url", "")
    account.access_token_enc = encrypt_text(page["access_token"])
    account.status = "ok"
    account.connected_at = utcnow()
    audit(session, user_id, None, "human", "connected_facebook", page=account.name)
    await session.commit()
    return _back("connected")


@router.get("/status")
async def status(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    account = await session.scalar(select(FacebookPage).where(FacebookPage.user_id == user.id))
    if account is None:
        return {"connected": False, "configured": facebook_api.configured()}
    out = {"connected": True, "configured": facebook_api.configured(), "page_id": account.page_id, "name": account.name,
           "picture_url": account.picture_url}
    token = decrypt_text(account.access_token_enc)
    if not token:
        return {**out, "ok": False, "error": "Stored token can't be read; reconnect Facebook"}
    try:
        info = await facebook_api.page_info(account.page_id, token)
    except facebook_api.FacebookError as exc:
        account.status = "error"
        await session.commit()
        return {**out, "ok": False, "error": str(exc)}
    account.status, account.name = "ok", info.get("name", account.name)
    await session.commit()
    return {**out, "ok": True, "followers": info.get("followers_count")}


@router.delete("")
async def disconnect(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    account = await session.scalar(select(FacebookPage).where(FacebookPage.user_id == user.id))
    if account:
        await session.delete(account)
        await session.commit()
    return {"ok": True}
