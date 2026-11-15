"""Logging: one call at startup, then `from loguru import logger` anywhere."""

import sys
from pathlib import Path

from loguru import logger


def setup_logging(level: str = "INFO", log_dir: str = "logs") -> None:
    # loguru starts with a default console handler; remove it so we control
    # the level and don't get duplicate lines.
    logger.remove()

    # 1) Console: what you watch while developing (and what systemd/Docker capture).
    logger.add(sys.stderr, level=level)

    # 2) File: the history you read after something went wrong at 3 AM.
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger.add(
        Path(log_dir) / "nerkhbot.log",
        level=level,
        rotation="10 MB",     # start a new file when this one reaches 10 MB
        retention="30 days",  # delete rotated files older than a month
        encoding="utf-8",     # Persian text in log lines must not break
        enqueue=True,         # write through a queue: safe with async code
    )
