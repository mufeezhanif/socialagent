import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import AuditEvent, Draft, Job, TasteMemory, User
from app.routes import brand as brand_routes
from app.services import taste
from app.services.audit import audit
from app.worker import tasks


@pytest_asyncio.fixture
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(taste, "SessionLocal", maker)
    monkeypatch.setattr(tasks, "SessionLocal", maker)
    monkeypatch.setattr(taste.llm, "any_configured", lambda: False)
    async with maker() as session:
        session.add(User(id="u1", email="a@b.c", password_hash="x"))
        await session.commit()
    yield maker
    await engine.dispose()


async def add_human(maker, action, **detail):
    async with maker() as session:
        audit(session, "u1", None, "human", action, **detail)
        await session.commit()


def test_rule_based_needs_repeats():
    one = [{"type": "requested_changes", "request": "remove the emojis"}]
    assert taste.rule_based([], one) == []
    sigs = [
        {"type": "requested_changes", "request": "no emojis please"},
        {"type": "requested_changes", "request": "remove emoji, and make it 30 seconds"},
        {"type": "requested_changes", "request": "cut it to 30s"},
        {"type": "requested_style", "style": "hype"},
        {"type": "requested_style", "style": "hype"},
    ]
    out = taste.rule_based(["Mine"], sigs)
    assert out[0] == "Mine"
    assert {"No emojis in captions", "Keeps Reels around 30 s", "Likes the hype style"} <= set(out)
    assert taste.rule_based(out, sigs) == out  # no duplicates on a re-run


def test_clean_notes():
    assert taste.clean_notes(["  a  ", "A", "", "b" * 200]) == ["a", "b" * 120]
    assert len(taste.clean_notes([str(i) for i in range(20)])) == taste.MAX_NOTES


@pytest.mark.asyncio
async def test_put_validation(db):
    user = User(id="u1", email="a@b.c", password_hash="x")
    async with db() as session:
        for bad in (["ok", "  "], [f"n{i}" for i in range(9)], ["x" * 121]):
            with pytest.raises(HTTPException) as exc:
                await brand_routes.update_taste(brand_routes.TasteBody(notes=bad), user, session)
            assert exc.value.status_code == 400
        out = await brand_routes.update_taste(brand_routes.TasteBody(notes=["  No emojis  ", "Short hooks"]), user, session)
        assert out["notes"] == ["No emojis", "Short hooks"]
        assert (await brand_routes.clear_taste(user, session))["notes"] == []


@pytest.mark.asyncio
async def test_notes_flow_into_brand_dict(db):
    async with db() as session:
        session.add(TasteMemory(user_id="u1", notes=["Keeps Reels around 30 s"], signals_seen=2))
        draft = Draft(user_id="u1", channel="web", chat_ref="u1", status="processing", revision_notes=[])
        session.add(draft)
        await session.commit()
        draft_id = draft.id
    _, _, brand = await tasks._load(draft_id)
    assert brand["learned_style"] == ["Keeps Reels around 30 s"]


@pytest.mark.asyncio
async def test_learn_is_noop_below_two_signals(db):
    await add_human(db, "requested_changes", notes="no emojis")
    await taste.learn(Job(kind="learn_taste", payload={"user_id": "u1"}))
    async with db() as session:
        assert await session.get(TasteMemory, "u1") is None
        await taste.queue_learning(session, "u1")
        assert await session.scalar(select(Job.id)) is None


@pytest.mark.asyncio
async def test_learn_saves_notes_and_audits_once(db):
    await add_human(db, "requested_changes", notes="no emojis")
    await add_human(db, "requested_changes", notes="remove the emoji")
    async with db() as session:
        await taste.queue_learning(session, "u1")
        await taste.queue_learning(session, "u1")  # one waiting job per user
        await session.commit()
        assert len((await session.scalars(select(Job))).all()) == 1
    job = Job(kind="learn_taste", payload={"user_id": "u1"})
    await taste.learn(job)
    await taste.learn(job)  # nothing new: no second audit event
    async with db() as session:
        memory = await session.get(TasteMemory, "u1")
        assert memory.notes == ["No emojis in captions"] and memory.signals_seen == 2
        events = (await session.scalars(select(AuditEvent).where(AuditEvent.action == "learned_taste"))).all()
        assert len(events) == 1 and events[0].detail["notes"] == ["No emojis in captions"]
