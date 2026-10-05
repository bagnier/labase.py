"""The one logging chain: JSON in production, console in development (``LOG_DEBUG``).

Our structlog calls and the libraries' stdlib ``logging`` meet in the terminal chain of
:class:`structlog.stdlib.ProcessorFormatter`, so the sink and capture tees sit there only: in the
structlog list they would see our lines twice.

The level is live (AGENTS: nothing escapes the log chain): loggers are not cached, so each call
reads the current one.
"""

import asyncio
import logging
import sys
import threading
from typing import Any

import structlog

from apps.shared.logs.capture import capture_processor
from apps.shared.logs.sink import flush_to_files, log_processor
from apps.shared.settings.env import get_technical_settings

log = structlog.get_logger(__name__)

# No ``DEBUG``: nothing writes below ``INFO``.
_LEVELS = {
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

DEFAULT_LEVEL = "INFO"


def apply_log_level(name: str) -> None:
    """Set the level of both structlog and the stdlib root logger; an unknown name is ignored."""
    level = _LEVELS.get(str(name).upper())
    if level is None:
        return
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(level))
    logging.getLogger().setLevel(level)


def _shared_processors() -> list[structlog.types.Processor]:
    """What every line carries; also the ``foreign_pre_chain`` for library lines."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]


# Everything else on the chain is a library. Scripts never call ``setup_logging``.
_OUR_PACKAGE = "apps."

_FOREIGN_FLOOR = logging.WARNING


class _ForeignFloor(logging.Filter):
    """Hold library loggers to WARNING and above.

    A stdlib filter, not a processor: ``ProcessorFormatter`` does not honour ``DropEvent``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith(_OUR_PACKAGE):
            return True
        return record.levelno >= _FOREIGN_FLOOR


def _renderer() -> structlog.types.Processor:
    if get_technical_settings().log_debug:
        return structlog.dev.ConsoleRenderer()
    return structlog.processors.JSONRenderer()


# Exceptions no ``except`` sees. Python's default hooks print them to stderr, outside the chain;
# routed here they are ``error`` lines with an exception, which capture turns into issues.


def _log_escaped(event: str, exc: BaseException, **context: Any) -> None:
    log.error(event, exc_info=exc, **context)


def _on_thread_exception(args: threading.ExceptHookArgs) -> None:
    if args.exc_value is None:
        return
    _log_escaped(
        "process.thread_crashed",
        args.exc_value,
        thread=args.thread.name if args.thread else None,
    )


def _on_process_exception(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
    # Not bugs.
    if isinstance(exc, KeyboardInterrupt | SystemExit):
        sys.__excepthook__(exc_type, exc, tb)
        return
    _log_escaped("process.crashed", exc)
    # No drain is left to take the line anywhere, nor a loop and database to open an issue: this
    # line on disk is all the crash leaves. A graceful stop drains instead (``CaptureDrain.stop``).
    flush_to_files()


def _on_unraisable(args: Any) -> None:
    if args.exc_value is None:
        return
    _log_escaped("process.unraisable", args.exc_value, during=repr(args.object))


def _on_loop_exception(_loop: Any, context: dict[str, Any]) -> None:
    exc = context.get("exception")
    detail = str(context.get("message") or "unhandled error in the event loop")
    if exc is None:
        # Nothing raised ("Task was destroyed but it is pending!" at shutdown): not a bug.
        log.warning("process.loop_error", detail=detail)
        return
    _log_escaped("process.task_crashed", exc, detail=detail)


async def catch_loop_exceptions() -> None:
    """Startup hook routing the running loop's unhandled exceptions to the chain; the loop does
    not exist yet when :func:`setup_logging` runs."""
    asyncio.get_running_loop().set_exception_handler(_on_loop_exception)


def _catch_escaping_exceptions() -> None:
    """Point Python's three exception hooks at the chain — threads, process exit, ``__del__``."""
    threading.excepthook = _on_thread_exception
    sys.excepthook = _on_process_exception
    sys.unraisablehook = _on_unraisable


def setup_logging() -> None:
    level = _LEVELS[DEFAULT_LEVEL]
    shared = _shared_processors()

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        # A stdlib logger, so ``add_logger_name`` gets a name.
        logger_factory=structlog.stdlib.LoggerFactory(),
        # A cached logger keeps its level; apply_log_level needs each call to re-read it.
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ForeignFloor())
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                # Before ``format_exc_info``, which turns the live exception into text.
                capture_processor,
                structlog.processors.format_exc_info,
                log_processor,
                _renderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # ``warnings.warn`` otherwise goes straight to stderr.
    logging.captureWarnings(capture=True)

    _catch_escaping_exceptions()
