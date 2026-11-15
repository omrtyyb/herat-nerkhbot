"""Collector logic, tested with a fake Telegram client (no network, no account)."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from nerkhbot import storage
from nerkhbot.collectors.telegram import TelegramCollector, message_to_row
from nerkhbot.db import RawMessage, RawMessageEdit, init_db, make_engine, make_session_factory

NOW = datetime.now(timezone.utc)
CHAT_ID = -1001234


def fake_msg(id: int, text: str = "سکه ۴۵٬۰۰۰٬۰۰۰", days_ago: float = 0, **extra):
    fields = dict(id=id, message=text, date=NOW - timedelta(days=days_ago),
                  views=5, media=None, action=None, edit_date=None)
    return SimpleNamespace(**{**fields, **extra})


class FakeClient:
    """Mimics the one Telethon method the backfill uses."""

    def __init__(self, messages):
        self.messages = messages
        self.fail_times = 0

    def iter_messages(self, entity, reverse=False, min_id=0, offset_date=None):
        async def gen():
            if self.fail_times:
                self.fail_times -= 1
                raise ConnectionError("network down")
            for m in sorted(self.messages, key=lambda m: m.id):
                if m.id > min_id and (offset_date is None or m.date > offset_date):
                    yield m
        return gen()


@pytest.fixture
def collector():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    Session = make_session_factory(engine)
    settings = SimpleNamespace(backfill_days=60, catchup_minutes=10, channels=["rates"])
    c = TelegramCollector(settings, Session, client=FakeClient([]))
    with Session.begin() as s:
        source_id = storage.upsert_source(s, "telegram", "1234", "rates", "Rates").id
    c._channels[CHAT_ID] = (SimpleNamespace(username="rates"), source_id)
    return c


def texts(collector, model=RawMessage):
    with collector.Session() as s:
        return s.scalars(select(model.text).order_by(model.id)).all()


def test_message_to_row():
    row = message_to_row(fake_msg(7, "دلار ۱۲۳", media=object()))
    assert row["message_id"] == 7 and row["text"] == "دلار ۱۲۳" and row["has_media"] is True


def test_photo_only_post_has_empty_text():
    assert message_to_row(fake_msg(1, text=None))["text"] == ""


def test_service_messages_are_skipped():
    assert message_to_row(fake_msg(1, action="pinned")) is None


def test_first_backfill_respects_backfill_days(collector):
    collector.client.messages = [fake_msg(1, "old", days_ago=90), fake_msg(2, "recent", days_ago=3)]
    assert asyncio.run(collector.backfill_channel(CHAT_ID)) == 1
    assert texts(collector) == ["recent"]


def test_backfill_days_zero_fetches_everything(collector):
    collector.settings.backfill_days = 0
    collector.client.messages = [fake_msg(1, days_ago=900), fake_msg(2)]
    assert asyncio.run(collector.backfill_channel(CHAT_ID)) == 2


def test_backfill_resumes_after_newest_saved_post(collector):
    collector.client.messages = [fake_msg(i) for i in range(1, 251)]
    assert asyncio.run(collector.backfill_channel(CHAT_ID)) == 250
    assert asyncio.run(collector.backfill_channel(CHAT_ID)) == 0  # nothing new
    collector.client.messages.append(fake_msg(251))
    assert asyncio.run(collector.backfill_channel(CHAT_ID)) == 1


def test_backfill_retries_on_network_error(collector, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)  # don't really wait between retries
    collector.client.messages = [fake_msg(1)]
    collector.client.fail_times = 2
    assert asyncio.run(collector.backfill_channel(CHAT_ID)) == 1


_real_sleep = asyncio.sleep


async def _no_sleep(_seconds):
    await _real_sleep(0)


def test_catch_up_survives_a_failing_channel(collector, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    collector.client.fail_times = 99
    asyncio.run(collector.catch_up())  # must not raise


def test_live_new_message_and_edit(collector):
    async def scenario():
        event = SimpleNamespace(chat_id=CHAT_ID, message=fake_msg(10, "v1"))
        await collector._on_new_message(event)
        await collector._on_new_message(event)  # delivered twice: still one row
        edited = fake_msg(10, "v2", edit_date=NOW + timedelta(minutes=5))
        await collector._on_edited_message(SimpleNamespace(chat_id=CHAT_ID, message=edited))

    asyncio.run(scenario())
    assert texts(collector) == ["v1"]
    assert texts(collector, RawMessageEdit) == ["v2"]
