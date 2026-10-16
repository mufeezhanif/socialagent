from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import User
from app.security import SESSION_COOKIE, read_session_token


async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = read_session_token(token) if token else None
    user = await session.get(User, user_id) if user_id else None
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def is_admin(user: User) -> bool:
    return user.email.lower() in settings.admin_email_set


async def admin_user(user: User = Depends(current_user)) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admins only")
    return user
