"""structlog configuration — JSON in production, pretty console in dev.

The level starts from the environment but is admin-tunable from the console and applies
live, with no restart (README: observability). Loggers are not cached so every call re-reads
the current level.
"""

import logging
import sys

import structlog

from apps.shared.config import get_technical_settings

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def default_log_level() -> str:
    """The env-driven starting level — also the seed of the console's `log_level` setting."""
    return "DEBUG" if get_technical_settings().log_debug else "INFO"


def apply_log_level(name: str) -> None:
    """Re-point structlog's filter and the stdlib root logger — runtime console control.

    Unknown names are ignored (the current level survives a bad value).
    """
    level = _LEVELS.get(str(name).upper())
    if level is None:
        return
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(level))
    logging.getLogger().setLevel(level)


def setup_logging() -> None:
    settings = get_technical_settings()
    level = _LEVELS[default_log_level()]

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.log_debug:
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        # Cached loggers would keep the wrapper class they were born with —
        # runtime level changes (apply_log_level) need every call to re-read it.
        cache_logger_on_first_use=False,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )
