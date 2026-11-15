"""All database writes and reads the collectors need.

Collectors never build SQL themselves; they call these functions. Every
function takes an open session and does NOT commit: the caller decides where
the transaction ends, e.g.

    with Session.begin() as session:      # commits on success, rolls back on error
        save_messages(session, source.id, rows)
"""

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from nerkhbot.db import Observation, ParseLog, RawMessage, RawMessageEdit, Source

BATCH_SIZE = 100  # rows per INSERT statement; keeps us under SQLite's parameter limit


def _insert_ignore(session: Session, model, rows: list[dict]) -> int:
    """INSERT rows, silently skipping any that hit a unique constraint.

    Returns how many rows were actually inserted.
    """
    if not rows:
        return 0
    # "ON CONFLICT DO NOTHING" is not standard SQL, so SQLAlchemy exposes it
    # per database. Pick the right one for whatever we're connected to.
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    elif dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        raise NotImplementedError(f"unsupported database: {dialect}")

    inserted = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        result = session.execute(insert(model).values(batch).on_conflict_do_nothing())
        inserted += result.rowcount
    return inserted


def upsert_source(
    session: Session,
    kind: str,
    external_id: str,
    name: str | None = None,
    title: str | None = None,
) -> Source:
    """Find the source by its stable id, or create it. Refresh its labels."""
    source = session.scalar(
        select(Source).where(Source.kind == kind, Source.external_id == external_id)
    )
    if source is None:
        source = Source(kind=kind, external_id=external_id)
        session.add(source)
    source.name = name
    source.title = title
    session.flush()  # send to the DB now so source.id is available
    return source


def last_message_id(session: Session, source_id: int) -> int | None:
    """The newest message_id we have for this source (None if we have nothing)."""
    return session.scalar(
        select(func.max(RawMessage.message_id)).where(RawMessage.source_id == source_id)
    )


def save_messages(session: Session, source_id: int, rows: list[dict]) -> int:
    """Save posts; ones we already have are skipped. Returns the number of new rows.

    Each row: {"message_id", "text", "posted_at", "views", "has_media"}
    """
    return _insert_ignore(
        session, RawMessage, [{**row, "source_id": source_id} for row in rows]
    )


def save_edit(session: Session, source_id: int, row: dict, edited_at: datetime) -> bool:
    """Record a new version of a post. Returns True if a new version was stored.

    Telegram also sends "edited" events when only the view count or reactions
    change, so we store a version only when the text really differs from the
    latest text we know.
    """
    # If we never saw the original (e.g. it is older than our backfill window),
    # store this version as the raw message and stop.
    if save_messages(session, source_id, [row]):
        return False

    latest_edit = session.scalar(
        select(RawMessageEdit.text)
        .where(
            RawMessageEdit.source_id == source_id,
            RawMessageEdit.message_id == row["message_id"],
        )
        .order_by(RawMessageEdit.edited_at.desc())
        .limit(1)
    )
    if latest_edit is not None:
        known_text = latest_edit
    else:
        known_text = session.scalar(
            select(RawMessage.text).where(
                RawMessage.source_id == source_id,
                RawMessage.message_id == row["message_id"],
            )
        )
    if row["text"] == known_text:
        return False

    return bool(
        _insert_ignore(
            session,
            RawMessageEdit,
            [
                {
                    "source_id": source_id,
                    "message_id": row["message_id"],
                    "text": row["text"],
                    "edited_at": edited_at,
                }
            ],
        )
    )


def counts_by_source(session: Session) -> list[tuple[Source, int, datetime | None]]:
    """For the `stats` command: (source, number of messages, newest posted_at)."""
    stmt = (
        select(Source, func.count(RawMessage.id), func.max(RawMessage.posted_at))
        .outerjoin(RawMessage, RawMessage.source_id == Source.id)
        .group_by(Source.id)
        .order_by(Source.id)
    )
    return [tuple(r) for r in session.execute(stmt).all()]


# ----- parsed data (observations + parse_log) -------------------------------


def pending_messages(session: Session, limit: int = 500) -> list[RawMessage]:
    """Posts the parser has not looked at yet, oldest first."""
    stmt = (
        select(RawMessage)
        .outerjoin(ParseLog, ParseLog.raw_message_id == RawMessage.id)
        .where(ParseLog.raw_message_id.is_(None))
        .order_by(RawMessage.posted_at, RawMessage.message_id)
        .limit(limit)
    )
    return list(session.scalars(stmt))


def latest_observation(
    session: Session, source_id: int, market: str, currency: str
) -> Observation | None:
    """The most recent trustworthy price we have, used to spot sudden jumps."""
    return session.scalar(
        select(Observation)
        .where(
            Observation.source_id == source_id,
            Observation.market == market,
            Observation.currency == currency,
            Observation.status == "ok",
        )
        .order_by(Observation.observed_at.desc(), Observation.id.desc())
        .limit(1)
    )


def save_parse_result(
    session: Session,
    message: RawMessage,
    status: str,
    reason: str,
    parser_version: int,
    observations: list[dict],
) -> int:
    """Store what the parser found for one post. Returns the number of new price rows."""
    saved = _insert_ignore(
        session,
        Observation,
        [
            {
                **row,
                "raw_message_id": message.id,
                "source_id": message.source_id,
                "observed_at": message.posted_at,
                "parser_version": parser_version,
            }
            for row in observations
        ],
    )
    _insert_ignore(
        session,
        ParseLog,
        [
            {
                "raw_message_id": message.id,
                "status": status,
                "reason": reason[:255],
                "parser_version": parser_version,
            }
        ],
    )
    return saved


def reset_parsed(session: Session) -> None:
    """Delete all derived rows so everything can be parsed again. Raw posts are untouched."""
    session.execute(delete(Observation))
    session.execute(delete(ParseLog))


def parse_counts(session: Session) -> dict[str, int]:
    """For `stats`: how many posts are parsed / ignored / failed."""
    rows = session.execute(select(ParseLog.status, func.count()).group_by(ParseLog.status))
    return {status: count for status, count in rows}


def latest_rates(session: Session) -> list[Observation]:
    """The newest live quote per (market, currency)."""
    newest = (
        select(
            Observation.market,
            Observation.currency,
            func.max(Observation.observed_at).label("at"),
        )
        .where(Observation.kind == "quote")
        .group_by(Observation.market, Observation.currency)
        .subquery()
    )
    stmt = (
        select(Observation)
        .join(
            newest,
            (Observation.market == newest.c.market)
            & (Observation.currency == newest.c.currency)
            & (Observation.observed_at == newest.c.at),
        )
        .where(Observation.kind == "quote")
        .order_by(Observation.market, Observation.currency, Observation.id.desc())
    )
    seen, result = set(), []
    for obs in session.scalars(stmt):
        if (obs.market, obs.currency) not in seen:
            seen.add((obs.market, obs.currency))
            result.append(obs)
    return result
