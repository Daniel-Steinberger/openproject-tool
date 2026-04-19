"""File-based logging setup.

All `op.*` loggers route through a single rotating file handler so that errors —
including full stack traces from `logger.exception(...)` — land in one place that
the user can inspect after the TUI has exited.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

from op.config import Config

_LOGGER_NAME = 'op'


def default_log_path() -> Path:
    """XDG-compliant default for the diagnostic log file."""
    xdg_state = os.environ.get('XDG_STATE_HOME')
    base = Path(xdg_state) if xdg_state else Path.home() / '.local' / 'state'
    return base / 'openproject-tool' / 'op.log'


def setup_logging(config: Config) -> Path:
    """Attach a rotating file handler to the `op` logger. Returns the log file path."""
    log_path = config.logging.file or default_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(_coerce_level(config.logging.level))

    # Remove existing handlers so repeated setup calls don't stack up.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding='utf-8'
    )
    handler.setFormatter(
        logging.Formatter(
            '%(asctime)s  %(levelname)-7s  %(name)s  %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
    )
    logger.addHandler(handler)
    logger.propagate = False  # Don't spam stderr during TUI use.
    return log_path


def _coerce_level(level: str) -> int:
    try:
        return getattr(logging, level.upper())
    except AttributeError:
        return logging.INFO
