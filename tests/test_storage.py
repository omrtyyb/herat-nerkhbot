"""Storage rules, tested against a throwaway in-memory SQLite database."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from nerkhbot import storage
from nerkhbot.db import RawMessage, RawMessageEdit, init_db, make_engine, make_session_factory

T0 = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def row(message_id: int, text: str = "دلار ۱۲۳٬۴۵۰") -> dict:
    return {
        "message_id": message_id,
        "text": text,
        "posted_at": T0 + timedelta(minutes=message_id),
        "views": 10,
        "has_media": False,
    }


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    with make_session_factory(engine)() as s:
        yield s


@pytest.fixture
def source(session):
    return storage.upsert_source(session, "telegram", "1001", name="rates", title="Rates")


def test_upsert_source_is_idempotent_and_refreshes_labels(session, source):
    again = storage.upsert_source(session, "telegram", "1001", name="newname", title="Rates")
    assert again.id == source.id
    assert again.name == "newname"


def test_save_messages_skips_duplicates(session, source):
    assert storage.save_messages(session, source.id, [row(1), row(2)]) == 2
    assert storage.save_messages(session, source.id, [row(2), row(3)]) == 1
    assert session.scalar(select(func.count(RawMessage.id))) == 3


def test_duplicate_never_overwrites_original_text(session, source):
    storage.save_messages(session, source.id, [row(1, "original")])
    storage.save_messages(session, source.id, [row(1, "changed")])
    assert session.scalar(select(RawMessage.text)) == "original"


def test_large_batch(session, source):
    assert storage.save_messages(session, source.id, [row(i) for i in range(1, 251)]) == 250
    assert storage.last_message_id(session, source.id) == 250


def test_last_message_id(session, source):
    assert storage.last_message_id(session, source.id) is None
    storage.save_messages(session, source.id, [row(5), row(9), row(7)])
    assert storage.last_message_id(session, source.id) == 9


def test_edit_history(session, source):
    storage.save_messages(session, source.id, [row(1, "v1")])

    # same text (e.g. only views changed): nothing stored
    assert storage.save_edit(session, source.id, row(1, "v1"), T0 + timedelta(hours=1)) is False
    # real edits: one row per version
    assert storage.save_edit(session, source.id, row(1, "v2"), T0 + timedelta(hours=2)) is True
    assert storage.save_edit(session, source.id, row(1, "v2"), T0 + timedelta(hours=3)) is False
    assert storage.save_edit(session, source.id, row(1, "v3"), T0 + timedelta(hours=4)) is True

    assert session.scalar(select(RawMessage.text)) == "v1"  # original untouched
    edits = session.scalars(select(RawMessageEdit.text).order_by(RawMessageEdit.edited_at)).all()
    assert edits == ["v2", "v3"]


def test_edit_of_unseen_message_becomes_raw_message(session, source):
    assert storage.save_edit(session, source.id, row(42, "late"), T0) is False
    assert session.scalar(select(RawMessage.text)) == "late"
    assert session.scalar(select(func.count(RawMessageEdit.id))) == 0


def test_timestamps_come_back_as_utc(session, source):
    storage.save_messages(session, source.id, [row(1)])
    session.expire_all()
    msg = session.scalars(select(RawMessage)).one()
    assert msg.posted_at == T0 + timedelta(minutes=1)
    assert msg.posted_at.tzinfo is not None
    assert msg.fetched_at.tzinfo is not None


def test_counts_by_source(session, source):
    storage.save_messages(session, source.id, [row(1), row(2)])
    [(src, count, newest)] = storage.counts_by_source(session)
    assert (src.id, count) == (source.id, 2)
    assert newest == T0 + timedelta(minutes=2)
