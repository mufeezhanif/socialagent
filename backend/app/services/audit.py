from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent


def audit(session: AsyncSession, user_id: str, draft_id: str | None, actor: str, action: str, **detail) -> None:
    """actor: 'ai' | 'human' | 'system'. Shown on the dashboard timeline."""
    session.add(AuditEvent(user_id=user_id, draft_id=draft_id, actor=actor, action=action, detail=detail))
