"""Database tables (SQLAlchemy models) and engine/session setup.

Raw tables (written by collectors, never changed afterwards):
    sources            one row per thing we collect from (a Telegram channel, later a website)
    raw_messages       every post exactly as first seen; rows are never updated
    raw_message_edits  later versions of a post, when the channel edits it

Derived tables (built from raw_messages by the parser; safe to delete and rebuild):
    observations       one row per price quote read out of a post
    parse_log          one row per post: was it parsed, ignored, or did it fail?
"""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """A datetime column that is always UTC.

    SQLite has no timezone support and silently drops it, so a value saved as
    "14:00 UTC" would come back as a bare "14:00". This type converts to UTC on
    the way in and re-attaches UTC on the way out, so the code always sees
    timezone-aware datetimes on both SQLite and Postgres.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime not allowed; use timezone-aware UTC")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # "telegram" now, "website" later
    # Stable id given by the source itself. For Telegram: the numeric channel
    # id, which survives a username change.
    external_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255))   # current @username
    title: Mapped[str | None] = mapped_column(String(255))  # display title
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("kind", "external_id", name="uq_source_kind_external"),)


class RawMessage(Base):
    __tablename__ = "raw_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    message_id: Mapped[int] = mapped_column(BigInteger)  # Telegram's id inside the channel
    text: Mapped[str] = mapped_column(Text, default="")  # exactly as posted
    posted_at: Mapped[datetime] = mapped_column(UTCDateTime)   # when the channel posted it
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)  # when we saved it
    views: Mapped[int | None]
    has_media: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (
        # The dedupe rule: one row per (channel, message).
        UniqueConstraint("source_id", "message_id", name="uq_raw_source_message"),
        # Analysis will mostly ask "posts from channel X between two dates".
        Index("ix_raw_source_posted", "source_id", "posted_at"),
    )


class RawMessageEdit(Base):
    __tablename__ = "raw_message_edits"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    message_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text, default="")  # the text after this edit
    edited_at: Mapped[datetime] = mapped_column(UTCDateTime)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        # One row per version of a message.
        UniqueConstraint("source_id", "message_id", "edited_at", name="uq_edit_version"),
    )


# A price column. Decimal in Python (no float rounding surprises like
# 65.70 + 0.05 = 65.75000000000001); 6 decimal places is plenty for rates.
Price = Numeric(18, 6, asdecimal=True)


class Observation(Base):
    """One price quote, e.g. "Herat, 1 USD = 65.70 buy / 65.75 sell AFN"."""

    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_message_id: Mapped[int] = mapped_column(ForeignKey("raw_messages.id"))  # where it came from
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime)  # = the post's posted_at
    market: Mapped[str] = mapped_column(String(32))          # "herat"
    currency: Mapped[str] = mapped_column(String(3))         # "USD", "EUR", "PKR"
    quote_currency: Mapped[str] = mapped_column(String(3))   # "AFN": what the price is paid in
    unit: Mapped[int] = mapped_column(default=1)             # price is for this many units (PKR: 1000)
    buy: Mapped[Decimal] = mapped_column(Price)
    sell: Mapped[Decimal] = mapped_column(Price)
    kind: Mapped[str] = mapped_column(String(16))            # "quote" (live) or "close" (end of day)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # "ok" or "suspect"
    issues: Mapped[str] = mapped_column(String(255), default="")   # why suspect, comma-separated
    parser_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        # Parsing the same post twice can never create a second row.
        UniqueConstraint("raw_message_id", "market", "currency", name="uq_obs_message_market_currency"),
        # Analysis asks "USD between two dates".
        Index("ix_obs_currency_time", "currency", "observed_at"),
    )


class ParseLog(Base):
    """What the parser decided about each post."""

    __tablename__ = "parse_log"

    raw_message_id: Mapped[int] = mapped_column(ForeignKey("raw_messages.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))  # "parsed", "ignored" (not a quote), "failed"
    reason: Mapped[str] = mapped_column(String(255), default="")
    parser_version: Mapped[int]
    parsed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (Index("ix_parse_log_status", "status"),)


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    # For a SQLite file, make sure its folder (data/) exists.
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url)


def init_db(engine: Engine) -> None:
    """Create any missing tables. Safe to call on every start."""
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(engine, expire_on_commit=False)
