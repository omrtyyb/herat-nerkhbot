"""Command line entry point.

    nerkhbot login      one-time interactive Telegram login (creates the session file)
    nerkhbot backfill   fetch missing posts once, then exit
    nerkhbot run        backfill, then listen for new posts until stopped
    nerkhbot stats      how many posts are stored per channel, and how parsing went
    nerkhbot latest     print the most recent stored posts
    nerkhbot parse      turn stored posts into price rows (only the not-yet-parsed ones)
    nerkhbot rates      show the newest price per currency
    nerkhbot failed     show posts that looked like prices but could not be read
"""

import argparse
import asyncio
import sys

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select

from nerkhbot import pipeline, storage
from nerkhbot.config import get_settings
from nerkhbot.db import ParseLog, RawMessage, init_db, make_engine, make_session_factory
from nerkhbot.logging_setup import setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nerkhbot", description="Collect rate posts into a database.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="one-time interactive Telegram login")
    sub.add_parser("backfill", help="fetch missing posts once, then exit")
    sub.add_parser("run", help="backfill, then listen for new posts until stopped")
    sub.add_parser("stats", help="show stored post counts per channel")
    latest = sub.add_parser("latest", help="print the most recent stored posts")
    latest.add_argument("-n", type=int, default=5, help="how many posts (default 5)")
    parse = sub.add_parser("parse", help="turn stored posts into price rows")
    parse.add_argument(
        "--all", action="store_true",
        help="delete all parsed rows first and parse every post again (raw posts are kept)",
    )
    sub.add_parser("rates", help="show the newest price per currency")
    sub.add_parser("failed", help="show posts that looked like prices but could not be read")
    return parser


async def _telegram(command: str, settings, Session) -> None:
    # Imported and created here, inside the running event loop, because the
    # Telegram client must live in the same loop that runs it.
    from nerkhbot.collectors.telegram import TelegramCollector

    collector = TelegramCollector(settings, Session)
    if command == "login":
        await collector.login()
        await collector.client.disconnect()
    elif command == "backfill":
        await collector.run_backfill_once()
    else:
        await collector.run_forever()


def _stats(Session) -> None:
    with Session() as session:
        rows = storage.counts_by_source(session)
    if not rows:
        print("No sources yet. Run `nerkhbot backfill` first.")
        return
    for source, count, newest in rows:
        newest_text = f"{newest:%Y-%m-%d %H:%M} UTC" if newest else "-"
        print(f"#{source.id}  {source.kind}  @{source.name}  {count} posts  newest: {newest_text}")
    _print_parse_counts(Session)


def _print_parse_counts(Session) -> None:
    with Session() as session:
        counts = storage.parse_counts(session)
    if counts:
        print("    parsing: " + ", ".join(f"{n} {status}" for status, n in sorted(counts.items())))


def _parse(Session, reparse_all: bool) -> None:
    if reparse_all:
        with Session.begin() as session:
            storage.reset_parsed(session)
        print("Cleared parsed rows; parsing everything again.")
    totals = pipeline.parse_pending(Session)
    print(
        f"Posts: {totals['parsed']} parsed, {totals['ignored']} ignored (not prices), "
        f"{totals['failed']} failed.  New price rows: {totals['observations']} "
        f"({totals['suspect']} suspect)."
    )


def _rates(Session) -> None:
    with Session() as session:
        rates = storage.latest_rates(session)
    if not rates:
        print("No prices yet. Run `nerkhbot parse` first.")
    for r in rates:
        unit = f"{r.unit:,} {r.currency}"
        flag = "" if r.status == "ok" else f"  [suspect: {r.issues}]"
        print(
            f"{r.market:<8} {unit:>9} = {r.buy:.2f} buy / {r.sell:.2f} sell "
            f"{r.quote_currency}   ({r.observed_at:%Y-%m-%d %H:%M} UTC){flag}"
        )


def _failed(Session) -> None:
    with Session() as session:
        rows = session.execute(
            select(RawMessage, ParseLog.reason)
            .join(ParseLog, ParseLog.raw_message_id == RawMessage.id)
            .where(ParseLog.status == "failed")
            .order_by(RawMessage.posted_at)
        ).all()
    if not rows:
        print("No failed posts.")
    for message, reason in rows:
        print(f"--- message {message.message_id}  {message.posted_at:%Y-%m-%d %H:%M} UTC: {reason}")
        print(message.text)


def _latest(Session, n: int) -> None:
    with Session() as session:
        posts = session.scalars(
            select(RawMessage)
            .order_by(RawMessage.posted_at.desc(), RawMessage.message_id.desc())
            .limit(n)
        ).all()
    for post in reversed(posts):  # oldest of the selection first, newest at the bottom
        print(f"--- message {post.message_id}  {post.posted_at:%Y-%m-%d %H:%M} UTC ---")
        print(post.text or "(no text)")
    if not posts:
        print("No posts stored yet.")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    try:
        settings = get_settings()
    except ValidationError as error:
        # Show which settings are missing/wrong, without a long traceback.
        problems = ", ".join(str(e["loc"][0]).upper() for e in error.errors())
        sys.exit(f"Bad or missing settings in .env: {problems}")

    setup_logging(settings.log_level, settings.log_dir)
    engine = make_engine(settings.database_url)
    init_db(engine)
    Session = make_session_factory(engine)

    if args.command == "stats":
        _stats(Session)
    elif args.command == "latest":
        _latest(Session, args.n)
    elif args.command == "parse":
        _parse(Session, args.all)
    elif args.command == "rates":
        _rates(Session)
    elif args.command == "failed":
        _failed(Session)
    else:
        try:
            asyncio.run(_telegram(args.command, settings, Session))
        except KeyboardInterrupt:
            logger.info("Stopped by user")
        except RuntimeError as error:  # our own "not logged in" / "no channels" messages
            logger.error("{}", error)
            sys.exit(1)
        except ConnectionError as error:  # Telegram unreachable after Telethon's own retries
            logger.error("Could not reach Telegram: {}", error)
            sys.exit(1)
