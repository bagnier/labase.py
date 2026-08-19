"""The one logging chain — JSON in production, pretty console in dev.

Everything that logs in this process converges here: our own ``structlog`` calls and whatever
the libraries emit through stdlib ``logging``. The two meet inside
:class:`structlog.stdlib.ProcessorFormatter`, whose terminal chain is the one point both flows
cross — so the firehose and capture tees sit there, and nowhere else. Ours traverse two processor
lists and a library's only one, so a tee in the structlog list would count our lines twice.

The level starts from the environment but is admin-tunable from the console and applies
live, with no restart (README: observability). Loggers are not cached so every call re-reads
the current level.
"""

import asyncio
import logging
import sys
import threading
from typing import Any

import structlog

from apps.shared.config import get_technical_settings
from apps.shared.observability.capture import capture_processor
from apps.shared.observability.firehose import firehose_processor, flush_firehose

log = structlog.get_logger(__name__)

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


def _shared_processors() -> list[structlog.types.Processor]:
    """What every line carries, whoever wrote it — hence also the ``foreign_pre_chain`` that
    brings a library's stdlib line up to the same shape before the terminal chain."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]


# Our own code lives under one package; everything else on the chain is a library. Scripts are
# not here on purpose: they never call ``setup_logging``, so they have no chain to join.
_OUR_PACKAGE = "apps."

# A third-party logger joins the chain for what needs attention — a degradation or a bug —
# never for its chatter. One rule, rather than a table of library names to keep up to date.
_FOREIGN_FLOOR = logging.WARNING


class _ForeignFloor(logging.Filter):
    """Hold third-party loggers to WARNING and above; ours answer to the console level.

    A stdlib filter rather than a processor: it runs before the formatter, so a dropped line
    costs nothing downstream — and ``structlog.DropEvent`` is not honoured inside
    :class:`~structlog.stdlib.ProcessorFormatter`, which would let it escape to the caller.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith(_OUR_PACKAGE):
            return True
        return record.levelno >= _FOREIGN_FLOOR


def _renderer() -> structlog.types.Processor:
    if get_technical_settings().log_debug:
        return structlog.dev.ConsoleRenderer()
    return structlog.processors.JSONRenderer()


# Exceptions no ``except`` block ever sees. Python hands each to a hook of its own and, left at
# their defaults, they write a traceback to stderr — outside the chain, so neither the timeline
# nor the issue tracker learns of them. Routed here they are ordinary ``error`` lines carrying a
# live exception, which is exactly what the capture seam already folds into an issue.


def _log_escaped(event: str, exc: BaseException, **context: Any) -> None:
    log.error(event, exc_info=exc, **context)


def _on_thread_exception(args: threading.ExceptHookArgs) -> None:
    if args.exc_value is None:  # thread bootstrap teardown, nothing escaped
        return
    _log_escaped(
        "process.thread_crashed",
        args.exc_value,
        thread=args.thread.name if args.thread else None,
    )


def _on_process_exception(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
    # A Ctrl-C or a deliberate exit is how a process is *meant* to end: leave both to the
    # interpreter's own hook rather than filing them as bugs.
    if isinstance(exc, KeyboardInterrupt | SystemExit):
        sys.__excepthook__(exc_type, exc, tb)
        return
    _log_escaped("process.crashed", exc)
    # The writer task is gone by now, so nothing else would ever take this line to disk.
    flush_firehose()


def _on_unraisable(args: Any) -> None:
    if args.exc_value is None:
        return
    _log_escaped("process.unraisable", args.exc_value, during=repr(args.object))


def _on_loop_exception(_loop: Any, context: dict[str, Any]) -> None:
    exc = context.get("exception")
    detail = str(context.get("message") or "unhandled error in the event loop")
    if exc is None:
        # The loop complains about things that never raised — "Task was destroyed but it is
        # pending!" as it closes, a callback with a bad signature. Degraded, not a bug: calling
        # it a crash at ``error`` would cry wolf on every shutdown.
        log.warning("process.loop_error", detail=detail)
        return
    _log_escaped("process.task_crashed", exc, detail=detail)


async def catch_loop_exceptions() -> None:
    """Startup hook: point the running loop's unhandled-exception handler at the chain.

    Separate from the three hooks :func:`setup_logging` installs, which are process-wide and
    need nothing running; a loop only exists once the app does.
    """
    asyncio.get_running_loop().set_exception_handler(_on_loop_exception)


def _catch_escaping_exceptions() -> None:
    """Point Python's three exception hooks at the chain — threads, process exit, ``__del__``."""
    threading.excepthook = _on_thread_exception
    sys.excepthook = _on_process_exception
    sys.unraisablehook = _on_unraisable


def setup_logging() -> None:
    level = _LEVELS[default_log_level()]
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
        # A stdlib logger, so the name reaches ``add_logger_name`` — the print factory drops
        # every argument it is given, which is what made the logger name unobservable.
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Cached loggers would keep the wrapper class they were born with —
        # runtime level changes (apply_log_level) need every call to re-read it.
        cache_logger_on_first_use=False,
    )

    # 12-factor: one stream, stdout. The formatter renders both flows the same way.
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ForeignFloor())
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                # The plumbing keys go first: everything after this line is teed or
                # rendered, and neither the firehose nor a stored issue wants them.
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                # Capture reads the *live* exception, so it precedes ``format_exc_info``
                # — which then leaves the firehose a rendered traceback to store.
                capture_processor,
                structlog.processors.format_exc_info,
                firehose_processor,
                _renderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # ``warnings.warn`` has a channel of its own, straight to stderr. Routed through stdlib
    # ``logging`` it becomes an ordinary line on the chain, under the ``py.warnings`` logger.
    logging.captureWarnings(capture=True)

    _catch_escaping_exceptions()
