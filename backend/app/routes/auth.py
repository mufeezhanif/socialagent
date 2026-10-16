import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps import current_user, is_admin
from app.models import BrandProfile, InstagramAccount, User, WhatsAppLink, utcnow
from app.pipeline.render_hyperframes import hyperframes_available
from app.security import SESSION_COOKIE, SESSION_TTL_S, create_session_token, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["auth"])
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterBody(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginBody(BaseModel):
    email: str
    password: str


def _set_session(response: Response, user_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user_id),
        httponly=True,
        secure=settings.app_base_url.startswith("https://"),
        samesite="lax",
        max_age=SESSION_TTL_S,
        path="/",
    )


async def me_payload(session: AsyncSession, user: User) -> dict:
    ig = await session.scalar(select(InstagramAccount).where(InstagramAccount.user_id == user.id))
    wa = await session.scalar(select(WhatsAppLink).where(WhatsAppLink.user_id == user.id))
    pending = wa and wa.link_code and wa.link_code_expires_at and wa.link_code_expires_at > utcnow()
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "timezone": user.timezone,
        "is_admin": is_admin(user),
        "app_name": settings.app_name,
        "instagram": (
            {
                "username": ig.username,
                "account_type": ig.account_type,
                "profile_picture_url": ig.profile_picture_url,
                "status": ig.status,
            }
            if ig
            else None
        ),
        "whatsapp": (
            {
                "linked": bool(wa.verified_at),
                "phone": wa.phone,
                "pending_code": wa.link_code if pending else None,
            }
            if wa
            else None
        ),
        "instagram_configured": bool(settings.ig_app_id) or settings.publish_dry_run,
        "features": {"motion": hyperframes_available()},
    }


@router.post("/auth/register")
async def register(body: RegisterBody, response: Response, session: AsyncSession = Depends(get_session)):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if await session.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, password_hash=hash_password(body.password), name=body.name.strip()[:120],
                timezone=settings.default_timezone)
    session.add(user)
    await session.flush()
    session.add(BrandProfile(user_id=user.id))
    await session.commit()
    _set_session(response, user.id)
    return await me_payload(session, user)


@router.post("/auth/login")
async def login(body: LoginBody, response: Response, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    _set_session(response, user.id)
    return await me_payload(session, user)


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await me_payload(session, user)


@router.get("/config")
async def public_config():
    return {"app_name": settings.app_name, "privacy_contact": quote(settings.admin_emails.split(",")[0].strip())}
