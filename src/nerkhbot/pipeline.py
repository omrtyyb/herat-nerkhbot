"""Run the parser over stored posts and save the results.

    raw_messages --parse_post()--> observations (+ parse_log)

Safe to run at any time and as often as you like: it only looks at posts that
have no parse_log row yet, and saving is insert-or-ignore.
"""

from collections import Counter
from decimal import Decimal

from loguru import logger
from sqlalchemy.orm import sessionmaker

from nerkhbot import storage
from nerkhbot.parser import PARSER_VERSION, Quote, parse_post

MAX_JUMP = Decimal("0.10")  # more than 10% away from the previous price looks wrong
CONFIRMATIONS = 3  # ...unless the new price is repeated this many times: then it is real
BATCH = 500


def _mid(buy: Decimal, sell: Decimal) -> Decimal:
    return (buy + sell) / 2


def parse_pending(Session: sessionmaker) -> Counter:
    """Parse every not-yet-parsed post. Returns counts like {"parsed": 10, "observations": 12}."""
    totals: Counter = Counter()
    # Last trusted mid price per (source, market, currency), to spot jumps.
    last_mid: dict = {}

    while True:
        with Session.begin() as session:
            messages = storage.pending_messages(session, BATCH)
            if not messages:
                break
            for message in messages:
                result = parse_post(message.text)
                rows = [
                    _to_row(session, message.source_id, quote, last_mid)
                    for quote in result.quotes
                ]
                totals["observations"] += storage.save_parse_result(
                    session, message, result.status, result.reason, PARSER_VERSION, rows
                )
                totals[result.status] += 1
                totals["suspect"] += sum(1 for row in rows if row["status"] == "suspect")
                if result.status == "failed":
                    logger.warning(
                        "Could not parse message {}: {} | {!r}",
                        message.message_id, result.reason, message.text[:120],
                    )
    return totals


def _to_row(session, source_id: int, quote: Quote, last_mid: dict) -> dict:
    issues = list(quote.issues)
    key = (source_id, quote.market, quote.currency)
    if key not in last_mid:  # first time we meet this currency in this run: ask the DB
        previous = storage.latest_observation(session, source_id, quote.market, quote.currency)
        last_mid[key] = _mid(previous.buy, previous.sell) if previous else None

    mid = _mid(quote.buy, quote.sell)
    reference = last_mid[key]
    if reference and not issues and abs(mid - reference) / reference > MAX_JUMP:
        # A big jump is suspect, but a real market move repeats. Count how many
        # times in a row we have seen this same new price.
        candidate, seen = last_mid.get(("candidate", *key), (None, 0))
        seen = seen + 1 if candidate == mid else 1
        last_mid[("candidate", *key)] = (mid, seen)
        if seen < CONFIRMATIONS:
            issues.append("jump")
    if not issues:
        last_mid[key] = mid  # only trusted prices become the new reference
        last_mid.pop(("candidate", *key), None)

    return {
        "market": quote.market,
        "currency": quote.currency,
        "quote_currency": quote.quote_currency,
        "unit": quote.unit,
        "buy": quote.buy,
        "sell": quote.sell,
        "kind": quote.kind,
        "status": "suspect" if issues else "ok",
        "issues": ",".join(issues),
    }
