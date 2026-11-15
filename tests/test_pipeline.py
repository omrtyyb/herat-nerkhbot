"""Parsing stored posts into observations, end to end on an in-memory database."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from nerkhbot import pipeline, storage
from nerkhbot.db import Observation, ParseLog, RawMessage, init_db, make_engine, make_session_factory

T0 = datetime(2026, 11, 15, 5, 0, tzinfo=timezone.utc)


def usd(buy, sell):
    return f"هرات دالر به افغانی💵 {buy} خـرید {sell} فـروش"


@pytest.fixture
def Session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return make_session_factory(engine)


def add_posts(Session, texts, start_id=1):
    with Session.begin() as s:
        source = storage.upsert_source(s, "telegram", "1", "rates", "Rates")
        rows = [
            {"message_id": start_id + i, "text": t, "posted_at": T0 + timedelta(minutes=start_id + i),
             "views": 1, "has_media": False}
            for i, t in enumerate(texts)
        ]
        storage.save_messages(s, source.id, rows)


def observations(Session):
    with Session() as s:
        return s.scalars(select(Observation).order_by(Observation.id)).all()


def test_parse_pending_end_to_end(Session):
    add_posts(Session, [
        usd("65.70", "65.75"),
        "هرات کلدار افغانی 🇵🇰 233,50 خرید 234,00 فروش",
        "هرات تومان بانکی 💳 0.250 خرید  0.260 فروش",
        "دلار هرات 👆",
        "هرات دالر به افغانی فروش 65.75 خرید 65.70",
    ])
    totals = pipeline.parse_pending(Session)
    assert (totals["parsed"], totals["ignored"], totals["failed"], totals["observations"]) == (2, 2, 1, 2)

    usd_row, pkr_row = observations(Session)
    assert (usd_row.currency, usd_row.buy, usd_row.sell, usd_row.unit) == ("USD", D("65.70"), D("65.75"), 1)
    assert (pkr_row.currency, pkr_row.buy, pkr_row.unit, pkr_row.status) == ("PKR", D("233.50"), 1000, "ok")
    assert usd_row.observed_at == T0 + timedelta(minutes=1)  # the post's own time, in UTC
    with Session() as s:
        assert usd_row.raw_message_id == s.scalar(select(RawMessage.id).where(RawMessage.message_id == 1))


def test_running_twice_adds_nothing(Session):
    add_posts(Session, [usd("65.70", "65.75")])
    pipeline.parse_pending(Session)
    again = pipeline.parse_pending(Session)
    assert sum(again.values()) == 0
    assert len(observations(Session)) == 1


def test_only_new_posts_are_parsed_on_later_runs(Session):
    add_posts(Session, [usd("65.70", "65.75")])
    pipeline.parse_pending(Session)
    add_posts(Session, [usd("65.75", "65.80")], start_id=2)
    assert pipeline.parse_pending(Session)["observations"] == 1


def test_more_posts_than_one_batch(Session, monkeypatch):
    monkeypatch.setattr(pipeline, "BATCH", 10)
    add_posts(Session, [usd("65.70", "65.75")] * 35)
    assert pipeline.parse_pending(Session)["observations"] == 35


def test_sudden_jump_is_suspect_and_does_not_poison_later_rows(Session):
    add_posts(Session, [usd("65.70", "65.75"), usd("6.57", "6.58"), usd("65.75", "65.80")])
    pipeline.parse_pending(Session)
    assert [(o.status, o.issues) for o in observations(Session)] == [("ok", ""), ("suspect", "jump"), ("ok", "")]


def test_jump_is_checked_against_rows_from_earlier_runs(Session):
    add_posts(Session, [usd("65.70", "65.75")])
    pipeline.parse_pending(Session)
    add_posts(Session, [usd("165.70", "165.75")], start_id=2)
    pipeline.parse_pending(Session)
    assert observations(Session)[-1].status == "suspect"


def test_a_real_move_is_accepted_once_it_repeats(Session):
    add_posts(Session, [usd("65.70", "65.75")] + [usd("80.00", "80.10")] * 4)
    pipeline.parse_pending(Session)
    assert [o.status for o in observations(Session)] == ["ok", "suspect", "suspect", "ok", "ok"]


def test_reset_parsed_keeps_raw_posts_and_allows_reparse(Session):
    add_posts(Session, [usd("65.70", "65.75"), "دلار هرات 👆"])
    pipeline.parse_pending(Session)
    with Session.begin() as s:
        storage.reset_parsed(s)
    with Session() as s:
        assert s.scalar(select(func.count(Observation.id))) == 0
        assert s.scalar(select(func.count(ParseLog.raw_message_id))) == 0
        assert s.scalar(select(func.count(RawMessage.id))) == 2
    assert pipeline.parse_pending(Session)["observations"] == 1


def test_latest_rates_and_parse_counts(Session):
    add_posts(Session, [usd("65.70", "65.75"), usd("65.75", "65.80"), "دلار هرات 👆"])
    pipeline.parse_pending(Session)
    with Session() as s:
        [rate] = storage.latest_rates(s)
        assert (rate.currency, rate.buy) == ("USD", D("65.75"))
        assert storage.parse_counts(s) == {"parsed": 2, "ignored": 1}
