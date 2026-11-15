"""Telegram collector: fetch channel history, then keep up with new posts.

Three ways posts reach the database, all through the same storage functions:
    1. backfill   on start, fetch everything newer than what we already have
    2. live       Telegram pushes new/edited posts to us as they happen
    3. catch-up   every few minutes, run the backfill again as a safety net
"""

import asyncio
from datetime import timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from sqlalchemy.orm import sessionmaker
from telethon import TelegramClient, errors, events, utils
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from nerkhbot import pipeline, storage
from nerkhbot.config import Settings
from nerkhbot.db import utcnow

KIND = "telegram"
SAVE_EVERY = 100  # during backfill, write to the DB every 100 posts

# Temporary problems worth retrying. Anything else (bad channel name, not
# logged in, a bug) should fail immediately so we see it.
TRANSIENT_ERRORS = (ConnectionError, OSError, asyncio.TimeoutError, errors.ServerError)


def message_to_row(msg) -> dict | None:
    """Turn a Telethon message into the dict storage.save_messages() expects.

    Returns None for service messages ("channel photo changed", "pinned a
    message"), which are not posts.
    """
    if getattr(msg, "action", None) is not None:
        return None
    return {
        "message_id": msg.id,
        "text": msg.message or "",  # raw text, no formatting; "" for photo-only posts
        "posted_at": msg.date,      # timezone-aware UTC, straight from Telegram
        "views": getattr(msg, "views", None),
        "has_media": msg.media is not None,
    }


def _log_retry(retry_state) -> None:
    logger.warning(
        "Telegram call failed ({}), retry #{} soon",
        retry_state.outcome.exception(),
        retry_state.attempt_number,
    )


class TelegramCollector:
    def __init__(self, settings: Settings, session_factory: sessionmaker, client=None):
        self.settings = settings
        self.Session = session_factory
        if client is None:  # tests pass in a fake client instead
            Path(settings.tg_session).parent.mkdir(parents=True, exist_ok=True)
            client = TelegramClient(
                settings.tg_session,
                settings.tg_api_id,
                settings.tg_api_hash,
                # If Telegram says "slow down for N seconds" and N <= 300,
                # Telethon just sleeps and continues instead of raising.
                flood_sleep_threshold=300,
            )
        self.client = client
        # chat_id (as Telegram events report it) -> (channel entity, sources.id)
        self._channels: dict[int, tuple[object, int]] = {}
        # Only one backfill at a time (startup one vs. scheduled ones).
        self._lock = asyncio.Lock()

    # ----- login / connect -------------------------------------------------

    async def login(self) -> None:
        """Interactive, one-time: asks for phone, code (and 2FA password)."""
        await self.client.start()
        me = await self.client.get_me()
        logger.info("Logged in as {} (id {})", me.first_name, me.id)

    async def connect(self) -> None:
        """Non-interactive: for the server. Fails if `login` was never run."""
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError("Not logged in to Telegram. Run `nerkhbot login` first.")

    async def resolve_channels(self) -> None:
        """Look up each configured channel and register it in `sources`."""
        if not self.settings.channels:
            raise RuntimeError("No channels configured. Set TG_CHANNELS in .env")
        for name in self.settings.channels:
            entity = await self.client.get_entity(name)
            with self.Session.begin() as session:
                source = storage.upsert_source(
                    session,
                    KIND,
                    external_id=str(entity.id),
                    name=getattr(entity, "username", None),
                    title=getattr(entity, "title", None),
                )
                source_id = source.id
            self._channels[utils.get_peer_id(entity)] = (entity, source_id)
            logger.info("Channel @{} -> source #{}", name, source_id)

    # ----- 1. backfill -----------------------------------------------------

    @retry(
        retry=retry_if_exception_type(TRANSIENT_ERRORS),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, max=60),  # 2s, 4s, 8s, ... up to 60s
        before_sleep=_log_retry,
        reraise=True,
    )
    async def backfill_channel(self, chat_id: int) -> int:
        """Fetch every post newer than the newest one we have. Returns new-row count."""
        entity, source_id = self._channels[chat_id]

        with self.Session() as session:
            last_id = storage.last_message_id(session, source_id)

        if last_id is not None:
            window = {"min_id": last_id}  # resume: only ids greater than last_id
        elif self.settings.backfill_days > 0:
            window = {"offset_date": utcnow() - timedelta(days=self.settings.backfill_days)}
        else:
            window = {}  # first run with BACKFILL_DAYS=0: the whole history

        saved = 0
        batch: list[dict] = []
        # reverse=True -> oldest first, so if we crash halfway, the next run's
        # "newest id we have" is still a correct place to resume from.
        async for msg in self.client.iter_messages(entity, reverse=True, **window):
            row = message_to_row(msg)
            if row is not None:
                batch.append(row)
            if len(batch) >= SAVE_EVERY:
                saved += self._save(source_id, batch)
                batch = []
                logger.info("Backfill in progress: {} posts saved so far (up to {:%Y-%m-%d})", saved, row["posted_at"])
        saved += self._save(source_id, batch)
        return saved

    def _save(self, source_id: int, rows: list[dict]) -> int:
        if not rows:
            return 0
        with self.Session.begin() as session:
            return storage.save_messages(session, source_id, rows)

    def _parse_new_posts(self) -> None:
        """Turn freshly saved posts into price rows.

        Collecting matters more than parsing: if the parser has a bug, log it
        and carry on. The raw post is already safe and can be parsed later.
        """
        try:
            totals = pipeline.parse_pending(self.Session)
        except Exception:
            logger.exception("Parsing failed (raw posts are saved; run `nerkhbot parse` later)")
            return
        if totals["observations"]:
            logger.info("Parsed {} new prices", totals["observations"])

    # ----- 3. catch-up (also used as the startup backfill) ------------------

    async def catch_up(self) -> None:
        async with self._lock:
            for chat_id, (entity, _) in self._channels.items():
                name = getattr(entity, "username", None) or chat_id
                try:
                    saved = await self.backfill_channel(chat_id)
                except Exception:
                    # Log with traceback and move on; the next run tries again.
                    logger.exception("Backfill failed for {}", name)
                else:
                    if saved:
                        logger.info("Backfill {}: {} new posts", name, saved)
                    else:
                        logger.debug("Backfill {}: nothing new", name)
            self._parse_new_posts()

    # ----- 2. live updates --------------------------------------------------

    async def _on_new_message(self, event) -> None:
        _, source_id = self._channels[event.chat_id]
        row = message_to_row(event.message)
        if row is not None and self._save(source_id, [row]):
            logger.info("New post {} in source #{}", row["message_id"], source_id)
            self._parse_new_posts()

    async def _on_edited_message(self, event) -> None:
        _, source_id = self._channels[event.chat_id]
        row = message_to_row(event.message)
        if row is None:
            return
        edited_at = event.message.edit_date or utcnow()
        with self.Session.begin() as session:
            stored = storage.save_edit(session, source_id, row, edited_at)
        if stored:
            logger.info("Edit of post {} in source #{}", row["message_id"], source_id)

    # ----- entry points used by the CLI --------------------------------------

    async def run_backfill_once(self) -> None:
        await self.connect()
        try:
            await self.resolve_channels()
            await self.catch_up()
        finally:
            await self.client.disconnect()

    async def run_forever(self) -> None:
        await self.connect()
        scheduler = AsyncIOScheduler(timezone="UTC")
        try:
            await self.resolve_channels()

            # Register live handlers BEFORE backfilling, so a post that arrives
            # during the backfill is not lost (duplicates are harmless).
            chats = [entity for entity, _ in self._channels.values()]
            self.client.add_event_handler(self._on_new_message, events.NewMessage(chats=chats))
            self.client.add_event_handler(self._on_edited_message, events.MessageEdited(chats=chats))

            await self.catch_up()

            scheduler.add_job(
                self.catch_up,
                "interval",
                minutes=self.settings.catchup_minutes,
                max_instances=1,  # never two catch-ups at once
                coalesce=True,    # if several runs were missed, run just one
            )
            scheduler.start()
            logger.info("Listening for new posts (catch-up every {} min)", self.settings.catchup_minutes)
            await self.client.run_until_disconnected()
        finally:
            if scheduler.running:
                scheduler.shutdown(wait=False)
            await self.client.disconnect()
