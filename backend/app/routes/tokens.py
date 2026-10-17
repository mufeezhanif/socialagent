import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user
from app.models import ApiToken, User

router = APIRouter(prefix="/api/mcp/tokens", tags=["mcp"])
MAX_TOKENS = 5


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenBody(BaseModel):
    name: str = "AI assistant"


def _row(t: ApiToken) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "prefix": t.prefix,
        "created_at": t.created_at.isoformat(),
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
    }


@router.get("")
async def list_tokens(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at))).all()
    return [_row(t) for t in rows]


@router.post("")
async def create_token(body: TokenBody, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    count = await session.scalar(select(func.count()).select_from(ApiToken).where(ApiToken.user_id == user.id))
    if (count or 0) >= MAX_TOKENS:
        raise HTTPException(400, f"You can have up to {MAX_TOKENS} tokens. Revoke one first.")
    token = "sa_" + secrets.token_urlsafe(32)
    row = ApiToken(user_id=user.id, name=(body.name.strip() or "AI assistant")[:64], token_hash=hash_token(token), prefix=token[:10])
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {**_row(row), "token": token}  # plaintext is returned this once only


@router.delete("/{token_id}")
async def revoke_token(token_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    row = await session.get(ApiToken, token_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Token not found")
    await session.delete(row)
    await session.commit()
    return {"ok": True}
