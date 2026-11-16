# herat-nerkhbot

**English** | [فارسی](README.fa.md)

**A Telegram channel scraper for currency exchange rates, written in Python.** It scrapes exchange-rate posts from a Telegram channel with Telethon, stores every post safely in a SQLite database, and parses them into clean, structured price data (buy and sell rates) that you can analyse or use inside another project.

It was built for the Herat (Afghanistan) currency market channel [`@NerkhYab_Khorasan`](https://t.me/NerkhYab_Khorasan) and tracks the US dollar (USD), the euro (EUR) and the Pakistani rupee (PKR, "kaldar") against the afghani (AFN). The collector works with any public Telegram channel; the price parser is written for this channel's format.

> **Status:** version 0.1.0, early but working. History download and parsing have been verified on real data (3,539 posts gave 1,861 price rows with no failures). Live mode and long unattended runs have had limited real-world testing so far. See [Limitations](#limitations).

---

## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Getting Telegram API keys](#getting-telegram-api-keys)
- [Configuration](#configuration)
- [Quick start](#quick-start)
- [Commands](#commands)
- [The database](#the-database)
- [How parsing works](#how-parsing-works)
- [Using it inside your own project](#using-it-inside-your-own-project)
- [Running on a server](#running-on-a-server)
- [Project layout](#project-layout)
- [Development and tests](#development-and-tests)
- [Security and privacy](#security-and-privacy)
- [Responsible use](#responsible-use)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## What it does

- **Downloads history.** On the first run it fetches the last 20 days of posts (configurable).
- **Keeps up with new posts.** New and edited posts are received live from Telegram, and a safety check every 15 minutes (configurable) fills any gap left by a dropped connection or a restart.
- **Never loses the original.** Every post is stored exactly as it was first seen and is never changed. Edits are stored as separate versions.
- **Never duplicates.** The database itself refuses a second copy of the same post or the same price, so it is always safe to run things twice.
- **Parses prices.** Each post is read into structured rows: market, currency, buy, sell, time. Live quotes and end-of-day closing rates are told apart.
- **Flags doubtful data.** A price that looks wrong (buy above sell, a huge spread, a sudden jump) is kept but marked `suspect`, so you can exclude it.
- **Tells you when it cannot read something.** A post that looks like a price but does not match the known format is recorded as `failed`, so a change in the channel's style is noticed instead of silently losing data.
- **Can be rebuilt.** Because raw posts are kept, all parsed data can be deleted and re-created at any time with improved rules.

## How it works

```
                 Telegram channel
                        │
        ┌───────────────┼────────────────┐
        │               │                │
   1. backfill      2. live          3. catch-up
   (history on    (new + edited     (every 15 min,
     start)         posts pushed)    fills gaps)
        └───────────────┼────────────────┘
                        ▼
              raw_messages  (exact text, never changed)
              raw_message_edits  (later versions)
                        │
                     parser  (strict rules, text cleaned first)
                        ▼
              observations  (one row per price)
              parse_log     (parsed / ignored / failed per post)
                        │
                        ▼
        your analysis, dashboard, API or other project
```

The design separates **collecting** from **parsing**. Collecting only stores text. Parsing only reads stored text. If the parser has a bug, nothing is lost: fix it and run `nerkhbot parse --all`.

## Requirements

- Python 3.10 or newer (developed and tested on 3.13 and 3.14)
- A Telegram account, and API keys for it (free, see [below](#getting-telegram-api-keys))
- The account must be able to open the channel. For live updates it should also **join** the channel.

Main libraries: [Telethon](https://github.com/LonamiWebs/Telethon) (Telegram), [SQLAlchemy](https://www.sqlalchemy.org/) (database), [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) (configuration), [APScheduler](https://apscheduler.readthedocs.io/) (periodic job), [loguru](https://github.com/Delgan/loguru) (logging), [tenacity](https://tenacity.readthedocs.io/) (retries).

## Installation

**To use it** (as a tool or inside another project):

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install git+https://github.com/omrtyyb/herat-nerkhbot.git
```

**To develop it** (edit the code, run the tests):

```bash
git clone https://github.com/omrtyyb/herat-nerkhbot.git
cd herat-nerkhbot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Either way you get the `nerkhbot` command and the importable Python package `nerkhbot`.

> The project is named `herat-nerkhbot`; the command and the import name are the shorter `nerkhbot`.

## Getting Telegram API keys

The tool logs in as a normal Telegram user (not a bot), because bots cannot read channels they do not administer.

1. Open <https://my.telegram.org> and sign in with your phone number in international format (for example `+93...`).
2. Telegram sends a login code **inside the Telegram app** (a chat message, not an SMS). Enter it.
3. Click **API development tools**.
4. Fill in *App title* and *Short name* with anything (for example `nerkhbot`), choose *Desktop*, and create the application.
5. Copy **App api_id** (a number) and **App api_hash** (32 characters).

If the page shows only "ERROR" when creating the application, turn off any VPN or ad blocker, or try another browser.

These two values identify your application. The actual login to your account happens later with `nerkhbot login`.

## Configuration

All settings come from environment variables or from a file named `.env` in the folder you run the command from. Real environment variables win over `.env`.

Create `.env`:

```ini
# Telegram API (from https://my.telegram.org)
TG_API_ID=123456
TG_API_HASH=0123456789abcdef0123456789abcdef

# Where the login session is stored (creates data/nerkhbot.session)
TG_SESSION=data/nerkhbot

# Channels to collect, comma-separated: @name, name, or https://t.me/name
TG_CHANNELS=@NerkhYab_Khorasan

# First run: how many days of history to fetch (0 = everything)
BACKFILL_DAYS=20
# How often, in minutes, to re-check for missed posts
CATCHUP_MINUTES=15

DATABASE_URL=sqlite:///data/nerkhbot.db
LOG_LEVEL=INFO
LOG_DIR=logs
```

| Setting | Required | Default | Meaning |
|---|---|---|---|
| `TG_API_ID` | yes | | Number from my.telegram.org |
| `TG_API_HASH` | yes | | 32-character string from my.telegram.org |
| `TG_SESSION` | no | `data/nerkhbot` | Path of the login session file (`.session` is added) |
| `TG_CHANNELS` | yes, to collect | empty | One or more channels, comma-separated |
| `BACKFILL_DAYS` | no | `20` | Days of history fetched when the database is empty. `0` fetches all history |
| `CATCHUP_MINUTES` | no | `15` | Interval of the periodic safety check |
| `DATABASE_URL` | no | `sqlite:///data/nerkhbot.db` | SQLAlchemy database URL |
| `LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `LOG_DIR` | no | `logs` | Folder for `nerkhbot.log` (rotated at 10 MB, kept 30 days) |

Notes:

- Relative paths (`data/...`, `logs`) are relative to the folder you run the command from. Always run it from the same folder, or use absolute paths.
- `BACKFILL_DAYS` only matters when the database has no posts for a channel. After that the tool always continues from the newest post it has.

## Quick start

```bash
# 1. one-time login (asks for phone number, the code from Telegram, and your 2-step password if set)
nerkhbot login

# 2. download history and parse it
nerkhbot backfill

# 3. look at the result
nerkhbot stats
nerkhbot rates
nerkhbot latest -n 3

# 4. keep collecting until you press Ctrl+C
nerkhbot run
```

Example output of `nerkhbot rates`:

```
herat        1 EUR = 72.80 buy / 73.00 sell AFN   (2026-11-15 11:40 UTC)
herat    1,000 PKR = 233.50 buy / 234.00 sell AFN   (2026-11-15 11:40 UTC)
herat        1 USD = 65.70 buy / 65.75 sell AFN   (2026-11-15 11:40 UTC)
```

## Commands

Run `nerkhbot --help` for the list, or `python -m nerkhbot ...` if the command is not on your PATH.

| Command | What it does |
|---|---|
| `nerkhbot login` | One-time interactive login. Creates the session file so later commands never ask again. |
| `nerkhbot backfill` | Fetches every post that is missing, parses the new posts, then exits. Suitable for cron. |
| `nerkhbot run` | Backfills, then listens for new and edited posts and re-checks every `CATCHUP_MINUTES`. Runs until stopped. |
| `nerkhbot parse` | Parses stored posts that have not been parsed yet. |
| `nerkhbot parse --all` | Deletes all parsed rows and parses every stored post again. Raw posts are untouched. Use after changing parser rules. |
| `nerkhbot rates` | Shows the newest live quote for each market and currency. |
| `nerkhbot stats` | Shows the number of stored posts per channel, the newest post time, and parsed / ignored / failed counts. |
| `nerkhbot latest -n 5` | Prints the most recent stored posts as raw text. |
| `nerkhbot failed` | Lists posts that looked like prices but could not be read. |

Stopping with **Ctrl+C** is always safe. Everything already saved stays, and the next run continues from there.

## The database

SQLite by default (a single file, `data/nerkhbot.db`). All timestamps are stored in **UTC**.

There are two groups of tables. **Raw tables** are written by the collector and never modified. **Derived tables** are built from the raw tables by the parser and can be deleted and rebuilt.

### `sources` (raw)

One row per channel.

| Column | Meaning |
|---|---|
| `id` | Internal id |
| `kind` | `telegram` |
| `external_id` | Telegram's numeric channel id. Stable even if the username changes |
| `name` | Current username |
| `title` | Display title |
| `created_at` | When the row was created |

Unique on (`kind`, `external_id`).

### `raw_messages` (raw)

One row per post, exactly as first seen.

| Column | Meaning |
|---|---|
| `id` | Internal id |
| `source_id` | The channel (`sources.id`) |
| `message_id` | Telegram's message number inside the channel |
| `text` | The exact text. Empty for photo-only posts |
| `posted_at` | When the channel posted it |
| `fetched_at` | When this tool saved it |
| `views` | View count at the time of saving |
| `has_media` | Whether the post had a photo or file |

Unique on (`source_id`, `message_id`). This is the rule that prevents duplicates.

### `raw_message_edits` (raw)

One row per later version of a post, written when the channel edits it. Columns: `source_id`, `message_id`, `text`, `edited_at`, `fetched_at`. A version is stored only when the text really changed (Telegram also reports "edits" when only the view count changes).

### `observations` (derived)

One row per price.

| Column | Example | Meaning |
|---|---|---|
| `id` | | Internal id |
| `raw_message_id` | | The post it was read from (`raw_messages.id`) |
| `source_id` | | The channel |
| `observed_at` | `2026-11-15 11:40:04` | The post's time (UTC) |
| `market` | `herat` | City |
| `currency` | `USD` | The currency being priced: `USD`, `EUR`, `PKR` |
| `quote_currency` | `AFN` | The currency the price is paid in |
| `unit` | `1`, `1000` | The price is for this many units. Kaldar is quoted per 1,000 rupees |
| `buy` | `65.70` | Buy rate |
| `sell` | `65.75` | Sell rate |
| `kind` | `quote`, `close` | A live quote, or an end-of-day closing rate |
| `status` | `ok`, `suspect` | Whether the row passed the sanity checks |
| `issues` | `jump` | Why it is suspect, comma-separated. Empty when `ok` |
| `parser_version` | `1` | Version of the rules that produced the row |
| `created_at` | | When the row was written |

Unique on (`raw_message_id`, `market`, `currency`).

Read a row as: *in `market`, `unit` units of `currency` cost `buy`/`sell` in `quote_currency`*. For example `herat, 1000 PKR = 233.50 / 234.00 AFN`.

### `parse_log` (derived)

One row per post, recording the parser's decision.

| Column | Meaning |
|---|---|
| `raw_message_id` | The post |
| `status` | `parsed` (prices found), `ignored` (not a price post), `failed` (looked like a price but could not be read) |
| `reason` | Explanation for `failed` |
| `parser_version` | Version of the rules |
| `parsed_at` | When it was processed |

### Example queries

Daily closing rate of the dollar:

```sql
SELECT date(observed_at) AS day, buy, sell
FROM observations
WHERE currency = 'USD' AND kind = 'close' AND status = 'ok'
ORDER BY day;
```

Only the moments when the dollar rate changed:

```sql
SELECT observed_at, buy, sell
FROM (
  SELECT observed_at, buy, sell,
         LAG(buy)  OVER (ORDER BY observed_at, id) AS prev_buy,
         LAG(sell) OVER (ORDER BY observed_at, id) AS prev_sell
  FROM observations
  WHERE currency = 'USD' AND kind = 'quote' AND status = 'ok'
)
WHERE prev_buy IS NULL OR buy <> prev_buy OR sell <> prev_sell;
```

Daily low, high and average mid price per currency:

```sql
SELECT date(observed_at) AS day, currency,
       MIN(buy) AS low, MAX(sell) AS high,
       ROUND(AVG((buy + sell) / 2), 4) AS avg_mid,
       COUNT(*) AS quotes
FROM observations
WHERE kind = 'quote' AND status = 'ok'
GROUP BY day, currency
ORDER BY day, currency;
```

## How parsing works

### What the channel posts

Most posts are one-line quotes:

```
هرات دالر به افغانی💵 65.70 خـرید 65.75 فـروش
هرات یورو به افغانی 💶 72.80خرید 73.00 فروش
هرات کلدار افغانی 🇵🇰 233,50 خرید 234,00 فروش
```

At the end of each trading day there is a summary:

```
📌پایان معاملات📌

🗓️  شنبه | 1405.08.16

💵 دالر به افغانی
65.15 خرید | 65.20 فروش
...
```

The rest are advertisements, greetings and notices, some of which contain numbers and currency words.

### The rules

1. **Clean the text first.** Persian and Arabic digits become Latin digits, Arabic `ي` and `ك` become Persian `ی` and `ک`, the stretch character in `خـرید` is removed, invisible characters are removed, and the Persian decimal and thousands marks are converted.
2. **A price is only read in this exact shape:** `number خرید number فروش` (buy, then sell), optionally with `|` between them. Buy and sell are identified by their labels, never by position alone.
3. **The label names the currency.** The label is the text before the prices on the same line, or the line above (as in summaries). Known spellings: `دالر` / `دلار` / `usd` / `dollar`, `یورو` / `eur` / `euro`, `کلدار` / `روپیه پاکستان` / `pkr`.
4. **The label must say what the price is paid in** (`افغانی` → AFN). A tracked currency priced in something unknown is recorded as `failed`, not guessed.
5. **Currencies that are not tracked are skipped.** Toman lines are ignored on purpose.
6. **Numbers.** `65.70` and `233,50` are both decimals. `1,250` is one thousand two hundred and fifty. `1,250.5` is handled too.
7. **Market.** Taken from the label (`هرات` → `herat`; Kabul, Mazar and Kandahar are recognised). End-of-day summaries do not name a city, so they default to `herat`.
8. **Kind.** A post containing `پایان معاملات` ("end of trading") gives `close` rows; everything else gives `quote` rows.

Because of rule 2, an advertisement such as "دلار هرات به کانال ۲۶۵" can never become a price.

### Sanity flags

A row is stored with `status = suspect` and a reason in `issues` when:

| Issue | Meaning |
|---|---|
| `non_positive` | Buy or sell is zero or negative |
| `buy_above_sell` | Buy is higher than sell |
| `wide_spread` | Sell is more than 5% above buy |
| `jump` | The mid price is more than 10% away from the last trusted price. If the same new price is repeated 3 times in a row it is accepted as a real market move |

Suspect rows are kept, never deleted. Filter with `status = 'ok'`.

### Changing the rules

The rules live in `src/nerkhbot/parser.py`: the spelling lists (`CURRENCY_ALIASES`), units (`UNITS`), markets (`MARKETS`) and thresholds. After changing them, increase `PARSER_VERSION` and run:

```bash
nerkhbot parse --all
```

## Using it inside your own project

There are three ways, from loosest to tightest.

### 1. Read the database (any language)

Let `nerkhbot run` fill the database and read it from your own program. With pandas:

```python
import pandas as pd

df = pd.read_sql(
    "SELECT observed_at, currency, buy, sell FROM observations "
    "WHERE kind = 'quote' AND status = 'ok' ORDER BY observed_at",
    "sqlite:///data/nerkhbot.db",
    parse_dates=["observed_at"],
)
usd = df[df.currency == "USD"].set_index("observed_at")
print(usd.resample("1D")[["buy", "sell"]].last())
```

### 2. Use the Python package

Parse a piece of text (no database or Telegram needed):

```python
from nerkhbot.parser import parse_post

result = parse_post("هرات دالر به افغانی💵 65.70 خـرید 65.75 فـروش")
print(result.status)                 # "parsed"
for q in result.quotes:
    print(q.market, q.currency, q.buy, q.sell, q.quote_currency, q.unit, q.kind)
# herat USD 65.70 65.75 AFN 1 quote
```

Read the latest rates from the database:

```python
from nerkhbot import storage
from nerkhbot.db import make_engine, make_session_factory

Session = make_session_factory(make_engine("sqlite:///data/nerkhbot.db"))
with Session() as session:
    for rate in storage.latest_rates(session):
        print(rate.market, rate.currency, rate.buy, rate.sell, rate.observed_at)
```

Run the collector from your own code, passing settings directly instead of using `.env`:

```python
import asyncio

from nerkhbot.collectors.telegram import TelegramCollector
from nerkhbot.config import Settings
from nerkhbot.db import init_db, make_engine, make_session_factory
from nerkhbot.logging_setup import setup_logging

settings = Settings(
    tg_api_id=123456,
    tg_api_hash="0123456789abcdef0123456789abcdef",
    tg_channels="@NerkhYab_Khorasan",
)
setup_logging(settings.log_level, settings.log_dir)
engine = make_engine(settings.database_url)
init_db(engine)                      # creates missing tables
Session = make_session_factory(engine)


async def main():
    collector = TelegramCollector(settings, Session)
    await collector.run_backfill_once()   # or: await collector.run_forever()


asyncio.run(main())
```

The session file must already exist (run `nerkhbot login` once with the same `TG_SESSION`).

### 3. Call the commands

From a shell script, cron or another program: `nerkhbot backfill`, `nerkhbot parse`, `nerkhbot rates`.

## Running on a server

`nerkhbot run` is a long-running process. On a Linux server, a systemd service keeps it alive and restarts it after a crash or reboot. The following is an example to adapt, not a tested deployment recipe:

```ini
# /etc/systemd/system/nerkhbot.service
[Unit]
Description=herat-nerkhbot collector
After=network-online.target
Wants=network-online.target

[Service]
User=nerkhbot
WorkingDirectory=/opt/herat-nerkhbot
ExecStart=/opt/herat-nerkhbot/.venv/bin/nerkhbot run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now nerkhbot
journalctl -u nerkhbot -f
```

Steps on a new server: install, create `.env` in the working directory, run `nerkhbot login` there once (interactive), then start the service.

Alternative without a long-running process: run `nerkhbot backfill` from cron every N minutes. You lose live delivery and edit tracking, but timestamps stay exact because they come from Telegram.

Back up `data/nerkhbot.db` regularly. It is a single file.

## Project layout

```
herat-nerkhbot/
├── pyproject.toml              project definition and dependencies
├── .env.example                template for your settings
├── README.md / README.fa.md    documentation
├── LICENSE
├── src/nerkhbot/
│   ├── config.py               settings from .env / environment
│   ├── logging_setup.py        console + rotating file log
│   ├── db.py                   table definitions, engine, sessions
│   ├── storage.py              every database read and write
│   ├── parser.py               text -> prices (pure, no I/O)
│   ├── pipeline.py             runs the parser over stored posts
│   ├── collectors/
│   │   └── telegram.py         backfill, live updates, catch-up
│   ├── cli.py                  the `nerkhbot` command
│   └── __main__.py             enables `python -m nerkhbot`
└── tests/                      pytest suite
```

Created at run time and ignored by git: `.env`, `data/` (database and session file), `logs/`.

## Development and tests

```bash
pip install -e ".[dev]"
pytest -q
```

The tests need no Telegram account and no network. They use an in-memory database, a fake Telegram client, and real posts copied from the channel. They cover duplicate handling, edit history, resuming a backfill, retry on network errors, every parsing rule, the sanity flags and re-parsing.

## Security and privacy

- **The session file is your Telegram login.** Anyone who copies `data/nerkhbot.session` can read your chats and act as you, without a code. Keep it private, never commit it, never share it.
- **Never commit `.env`.** It holds your API hash. The included `.gitignore` excludes `.env`, `*.session`, `data/` and `logs/`.
- **Do not upload the project folder through the GitHub website.** That path ignores `.gitignore`. Use `git` from the command line.
- **Consider a separate Telegram account** for collecting, so a leaked session or a restriction never affects your personal account. Enable two-step verification either way.
- **Revoke access at any time** in Telegram under Settings → Devices by ending the session.
- **The tool only reads.** It never posts, comments, messages anyone, or collects subscriber information.

## Responsible use

- The tool reads content published by other people. Collecting public posts for your own analysis is the intended use.
- Republishing or selling collected data may need the channel owner's permission and may be restricted by law in your country. That is your responsibility.
- Telegram can restrict accounts that behave abusively. This tool makes few, small requests and waits when Telegram asks it to slow down, but you use your account at your own risk and must follow Telegram's Terms of Service.
- Collected data is not included in this repository.

## Limitations

- **The parser is specific to this channel's format.** Collecting works for any channel, but prices from a channel that writes them differently will be `ignored` or `failed` until rules are added.
- **Only USD, EUR and PKR against AFN are tracked.**
- **Kaldar is assumed to be quoted per 1,000 rupees.** If that is wrong for your channel, change `UNITS` in `parser.py`.
- **Edited posts are stored but not re-parsed.** The price row reflects the first version of the post.
- **Edits made while the tool was offline are not recovered.** Missed new posts are.
- **One Telegram account.** If it is logged out or restricted, collecting stops until you log in again.
- **`BACKFILL_DAYS` applies only to an empty database.** There is no command yet to fetch older history later.
- **No schema migrations.** New tables are created automatically, but changing an existing column needs manual work.
- **PostgreSQL is planned for but not yet tested.** The code avoids SQLite-only features and should work with a PostgreSQL URL and driver.
- **No web API, dashboard or alerts yet.**

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| `ModuleNotFoundError: No module named 'nerkhbot'` | The virtual environment is not active (`source .venv/bin/activate`), or the package is not installed in it (`pip install -e ".[dev]"`). |
| `command not found: nerkhbot` | Same as above. `python -m nerkhbot ...` also works. |
| `Bad or missing settings in .env: TG_API_ID, TG_API_HASH` | No `.env` in the current folder, or the values are missing. Run the command from the folder that contains `.env`. |
| `No channels configured. Set TG_CHANNELS in .env` | `TG_CHANNELS` is empty. |
| `Not logged in to Telegram. Run nerkhbot login first.` | No valid session file at `TG_SESSION`. Run `nerkhbot login`. |
| `Could not reach Telegram` | No network, or Telegram is blocked on your network. |
| my.telegram.org shows only "ERROR" | Turn off VPN and ad blocker, or try another browser. |
| Changed `BACKFILL_DAYS` but no older posts arrive | It only applies to an empty database. Delete `data/nerkhbot.db` and run `nerkhbot backfill` again. |
| `nerkhbot failed` lists posts | The channel used a format the parser does not know. Add a rule in `parser.py`, then `nerkhbot parse --all`. |
| Backfill prints nothing for a while | Normal on a quiet channel. A progress line appears after every 100 posts. |

## License

MIT. See [LICENSE](LICENSE).
