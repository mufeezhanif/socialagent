from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def normalize_db_url(url: str) -> tuple[str, dict]:
    """Turn provider URLs (postgres://...?sslmode=require) into asyncpg form."""
    connect_args: dict = {}
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgresql+asyncpg://"):
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        sslmode = query.pop("sslmode", None)
        query.pop("channel_binding", None)
        if sslmode and sslmode != "disable":
            connect_args["ssl"] = "require"
        url = urlunsplit(parts._replace(query=urlencode(query)))
    return url, connect_args


class Base(DeclarativeBase):
    pass


db_url, connect_args = normalize_db_url(settings.database_url)
if db_url.startswith("sqlite"):
    Path(db_url.split("///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(db_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
