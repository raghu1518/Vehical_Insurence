from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .config import SETTINGS


def setup_logging(name: str = "app") -> logging.Logger:
    log_dir = SETTINGS.logging.dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = (log_dir / f"{name}.log").resolve()

    logger = logging.getLogger()
    configured_level = SETTINGS.logging.level.upper()
    logger.setLevel(configured_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    has_file_handler = False
    for handler in logger.handlers:
        if isinstance(handler, TimedRotatingFileHandler):
            try:
                if Path(handler.baseFilename).resolve() == log_file:
                    has_file_handler = True
                    break
            except Exception:
                continue

    if not has_file_handler:
        file_handler = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    has_plain_console_handler = any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, TimedRotatingFileHandler)
        for handler in logger.handlers
    )
    if not has_plain_console_handler:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
