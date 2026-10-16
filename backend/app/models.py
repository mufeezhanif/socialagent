import secrets
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db import Base


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, returns aware UTC. Same behaviour on SQLite and Postgres."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class DraftStatus:
    PROCESSING = "processing"
    AWAITING_VIDEO_APPROVAL = "awaiting_video_approval"
    AWAITING_CHANGE_NOTES = "awaiting_change_notes"
    REVISING = "revising"
    AWAITING_CONTEXT = "awaiting_context"
    CAPTIONING = "captioning"
    AWAITING_CAPTION_CHOICE = "awaiting_caption_choice"
    AWAITING_PUBLISH_CHOICE = "awaiting_publish_choice"
    AWAITING_SCHEDULE_TIME = "awaiting_schedule_time"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    SAVED = "saved"
    DISCARDED = "discarded"
    FAILED = "failed"

    TERMINAL = {PUBLISHED, SAVED, DISCARDED}
    WORKING = {PROCESSING, REVISING, CAPTIONING, PUBLISHING}


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("u"))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Karachi")
    active_draft_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class WhatsAppLink(Base):
    __tablename__ = "whatsapp_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("w"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    phone: Mapped[str] = mapped_column(String(32), default="")
    jid: Mapped[str | None] = mapped_column(String(96), unique=True, nullable=True)
    jid_alt: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    link_code: Mapped[str | None] = mapped_column(String(16), unique=True, nullable=True)
    link_code_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class InstagramAccount(Base):
    __tablename__ = "instagram_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ig"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    ig_user_id: Mapped[str] = mapped_column(String(64))
    username: Mapped[str] = mapped_column(String(120), default="")
    account_type: Mapped[str] = mapped_column(String(32), default="")
    profile_picture_url: Mapped[str] = mapped_column(Text, default="")
    access_token_enc: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    connected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class BrandProfile(Base):
    __tablename__ = "brand_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    niche: Mapped[str] = mapped_column(String(200), default="")
    tone: Mapped[str] = mapped_column(String(200), default="friendly, confident")
    audience: Mapped[str] = mapped_column(String(200), default="")
    emoji_level: Mapped[str] = mapped_column(String(16), default="some")
    cta: Mapped[str] = mapped_column(String(200), default="")
    default_hashtags: Mapped[list] = mapped_column(JSON, default=list)
    banned_words: Mapped[list] = mapped_column(JSON, default=list)
    primary_color: Mapped[str] = mapped_column(String(9), default="#FFFFFF")
    accent_color: Mapped[str] = mapped_column(String(9), default="#FFD400")
    default_style: Mapped[str] = mapped_column(String(24), default="clean")
    preferred_post_time: Mapped[str] = mapped_column(String(5), default="19:00")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("d"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp")
    chat_ref: Mapped[str] = mapped_column(String(96), default="")
    status: Mapped[str] = mapped_column(String(32), default=DraftStatus.PROCESSING, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    style: Mapped[str] = mapped_column(String(24), default="clean")
    user_context: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_path: Mapped[str] = mapped_column(Text, default="")
    master_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_in: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_out: Mapped[float | None] = mapped_column(Float, nullable=True)

    probe: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    transcript: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    storyboard: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    edit_summary: Mapped[list | None] = mapped_column(JSON, nullable=True)
    revision_notes: Mapped[list] = mapped_column(JSON, default=list)

    caption_pack: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    caption_final: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtags_final: Mapped[list | None] = mapped_column(JSON, nullable=True)

    video_approved_rev: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption_approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    publish_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    publish_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    publish_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)

    ig_container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ig_media_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ig_permalink: Mapped[str | None] = mapped_column(Text, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("j"))
    kind: Mapped[str] = mapped_column(String(32), index=True)
    draft_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("m"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    draft_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    channel: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(4))  # in | out
    provider_message_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="text")
    body: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("a"))
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    draft_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(8))  # ai | human | system
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
