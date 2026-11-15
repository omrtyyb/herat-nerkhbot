"""Turn the text of a post into price quotes.

This module is pure: text in, data out. It never touches the database or
Telegram, which makes it easy to test with real posts.

The rules are deliberately strict. A price is only read when it is written as
    <number> خرید <number> فروش        (buy ... sell ...)
next to the name of a currency we track. Anything else is left alone, so ads
like "دلار هرات به کانال ۲۶۵" can never become a price.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# Bump this when the rules change, so rows can be traced to the rules that made them.
PARSER_VERSION = 1

MAX_SPREAD = Decimal("0.05")  # sell more than 5% above buy looks wrong

# ----- 1. cleaning ----------------------------------------------------------

_CHAR_MAP = str.maketrans(
    {
        **{persian: str(i) for i, persian in enumerate("۰۱۲۳۴۵۶۷۸۹")},
        **{arabic: str(i) for i, arabic in enumerate("٠١٢٣٤٥٦٧٨٩")},
        "ي": "ی",  # Arabic yeh  -> Persian yeh
        "ى": "ی",
        "ك": "ک",  # Arabic kaf  -> Persian kaf
        "٫": ".",  # Persian decimal separator
        "٬": ",",  # Persian thousands separator
        "ـ": None,  # kashida, the stretch in "خـرید"
        "‌": " ",   # zero-width non-joiner (half space)
        "​": None, "‍": None, "‎": None, "‏": None,  # invisible marks
        "⁠": None, "﻿": None,
        " ": " ",   # non-breaking space
    }
)


def normalize(text: str) -> str:
    """Make text predictable before matching: one spelling per letter and digit."""
    return text.translate(_CHAR_MAP)


# ----- 2. what we look for --------------------------------------------------

# Spellings per tracked currency. Checked on normalized text.
CURRENCY_ALIASES = {
    "USD": ("دالر", "دلار", "usd", "dollar"),
    "EUR": ("یورو", "eur", "euro"),
    "PKR": ("کلدار", "روپیه پاکستان", "pkr"),
}

# The price is quoted for this many units of the currency.
# Kaldar is quoted per 1,000 rupees (233.50 AFN for 1,000 PKR).
UNITS = {"USD": 1, "EUR": 1, "PKR": 1000}

# What the price is paid in.
QUOTE_CURRENCY_WORDS = {"افغانی": "AFN"}

MARKETS = {"هرات": "herat", "کابل": "kabul", "مزار": "mazar", "قندهار": "kandahar"}
DEFAULT_MARKET = "herat"  # end-of-day summaries do not name the city

CLOSE_MARKER = "پایان معاملات"  # "end of trading"

_NUMBER = r"\d+(?:[.,]\d+)*"
# "<number> خرید [|] <number> فروش"
_PRICES = re.compile(rf"({_NUMBER})\s*خرید\s*\|?\s*({_NUMBER})\s*فروش")
_HAS_LETTERS = re.compile(r"[^\W\d_]")


@dataclass(frozen=True)
class Quote:
    currency: str        # "USD"
    quote_currency: str  # "AFN"
    market: str          # "herat"
    unit: int            # 1 or 1000
    buy: Decimal
    sell: Decimal
    kind: str            # "quote" or "close"
    issues: tuple[str, ...] = ()


@dataclass
class ParseResult:
    status: str  # "parsed", "ignored", "failed"
    quotes: list[Quote] = field(default_factory=list)
    reason: str = ""


def to_decimal(number: str) -> Decimal:
    """'65.70' -> 65.70, '233,50' -> 233.50, '1,250' -> 1250, '1,250.5' -> 1250.5"""
    if "," in number and "." in number:
        number = number.replace(",", "")  # comma can only be a thousands separator
    elif "," in number:
        head, *groups = number.split(",")
        if all(len(g) == 3 for g in groups) and 1 <= len(head) <= 3:
            number = head + "".join(groups)  # 1,250 -> thousands separator
        elif len(groups) == 1:
            number = f"{head}.{groups[0]}"   # 233,50 -> decimal comma
        else:
            raise InvalidOperation(number)
    return Decimal(number)


def _find_currency(label: str) -> str | None:
    """The tracked currency named first in the label, if any."""
    lowered = label.lower()
    best: tuple[int, str] | None = None
    for code, aliases in CURRENCY_ALIASES.items():
        for alias in aliases:
            position = lowered.find(alias)
            if position != -1 and (best is None or position < best[0]):
                best = (position, code)
    return best[1] if best else None


def _first_word_match(label: str, table: dict[str, str]) -> str | None:
    for word, value in table.items():
        if word in label:
            return value
    return None


def mentions_tracked_currency(text: str) -> bool:
    return _find_currency(text) is not None


def parse_post(text: str) -> ParseResult:
    """Read every dollar / euro / kaldar price out of one post."""
    clean = normalize(text or "")
    kind = "close" if CLOSE_MARKER in clean else "quote"
    quotes: dict[tuple[str, str], Quote] = {}
    problems: list[str] = []

    previous_line = ""
    for line in clean.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _PRICES.search(line)
        if match is None:
            previous_line = line
            continue

        # The label is the text before the prices on the same line
        # ("هرات دالر به افغانی 65.70 خرید ..."), or, in summaries, the line above.
        label = line[: match.start()]
        if not _HAS_LETTERS.search(label):
            label = previous_line
        previous_line = line

        currency = _find_currency(label)
        if currency is None:
            continue  # a currency we don't track (e.g. toman): not an error

        quote_currency = _first_word_match(label, QUOTE_CURRENCY_WORDS)
        if quote_currency is None:
            problems.append(f"{currency}: no known quote currency in '{label.strip()[:40]}'")
            continue

        try:
            buy, sell = to_decimal(match.group(1)), to_decimal(match.group(2))
        except InvalidOperation:
            problems.append(f"{currency}: unreadable number in '{match.group(0)}'")
            continue

        issues = []
        if buy <= 0 or sell <= 0:
            issues.append("non_positive")
        elif buy > sell:
            issues.append("buy_above_sell")
        elif (sell - buy) / buy > MAX_SPREAD:
            issues.append("wide_spread")

        market = _first_word_match(label, MARKETS) or DEFAULT_MARKET
        quotes.setdefault(  # if a post repeats a currency, keep the first
            (market, currency),
            Quote(currency, quote_currency, market, UNITS[currency], buy, sell, kind, tuple(issues)),
        )

    if quotes:
        return ParseResult("parsed", list(quotes.values()), "; ".join(problems))
    if problems:
        return ParseResult("failed", reason="; ".join(problems)[:255])
    # Mentions our currency AND uses the buy/sell words, but nothing matched:
    # the channel may have changed its format. Surface it instead of dropping it.
    if mentions_tracked_currency(clean) and ("خرید" in clean or "فروش" in clean):
        return ParseResult("failed", reason="looks like a quote but did not match the pattern")
    return ParseResult("ignored")
