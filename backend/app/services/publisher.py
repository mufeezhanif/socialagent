"""Publishing with the human-approval gates enforced in code."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations import facebook_api, instagram_api
from app.models import Draft, FacebookPage, InstagramAccount
from app.security import decrypt_text, media_url
from app.services.captions import full_caption

log = logging.getLogger(__name__)


class GateError(RuntimeError):
    pass


class PublishError(RuntimeError):
    pass


def check_gates(draft: Draft) -> None:
    """No LLM output can reach Instagram: the human must have approved this exact revision, the caption and the post."""
    if draft.video_approved_rev is None or draft.video_approved_rev != draft.revision:
        raise GateError("the edited video for this revision was not approved")
    if not draft.caption_approved_at or not draft.caption_final:
        raise GateError("the caption was not approved")
    if not draft.publish_confirmed_at:
        raise GateError("posting was not confirmed")
    if not draft.master_path:
        raise GateError("no rendered video")


async def instagram_account(session: AsyncSession, user_id: str) -> InstagramAccount | None:
    return await session.scalar(select(InstagramAccount).where(InstagramAccount.user_id == user_id))


async def facebook_page(session: AsyncSession, user_id: str) -> FacebookPage | None:
    return await session.scalar(select(FacebookPage).where(FacebookPage.user_id == user_id))


async def publish_facebook(session: AsyncSession, draft: Draft) -> str | None:
    """Cross-post the same approved Reel to the connected Facebook Page. Returns the permalink, or None if no Page."""
    check_gates(draft)
    page = await facebook_page(session, draft.user_id)
    if page is None:
        return None
    token = decrypt_text(page.access_token_enc)
    if not token:
        raise PublishError("Facebook token unreadable; please reconnect Facebook")
    caption = full_caption(draft.caption_final or "", draft.hashtags_final or [])
    try:
        _, permalink = await facebook_api.publish_reel(page.page_id, token, draft.master_path, caption)
    except facebook_api.FacebookError as exc:
        raise PublishError(str(exc)) from exc
    return permalink


async def publish(session: AsyncSession, draft: Draft) -> tuple[str, str]:
    check_gates(draft)
    caption = full_caption(draft.caption_final or "", draft.hashtags_final or [])
    account = await instagram_account(session, draft.user_id)
    if account is None:
        if settings.publish_dry_run:
            log.warning("DRY RUN publish for draft %s", draft.id)
            return "dry-run", f"{settings.app_base_url}/app/drafts/{draft.id}?dry_run=1"
        raise PublishError("Instagram is not connected")
    token = decrypt_text(account.access_token_enc)
    if not token:
        raise PublishError("Instagram token unreadable; please reconnect Instagram")

    async def remember(container_id: str) -> None:
        draft.ig_container_id = container_id
        await session.commit()

    try:
        return await instagram_api.publish_reel(
            account.ig_user_id,
            token,
            media_url(draft.master_path, ttl_s=3 * 3600),
            caption,
            thumb_offset_ms=500,
            on_container=remember,
        )
    except instagram_api.InstagramError as exc:
        raise PublishError(str(exc)) from exc
