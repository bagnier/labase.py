"""One verdict for a failed call out of the process: a refusal or a breakage
(AGENTS: a broken dependency is a bug, a refusal is not).

GoTrue and Storage answer with an HTTP status, Postgres with a SQLSTATE; both mean the server
answered, and most answers are ordinary (a 4xx, an unmigrated table, a missing grant). The verdict
reads the shape of the answer, not the client class, which ``apps.shared`` could not import anyway.

Call :func:`log_dependency_failure` from the ``except`` block with the module's own logger: the
Timeline reads a line's app off its logger.
"""

from typing import Any

# On the exception (gotrue's ``AuthApiError``, storage3's ``StorageException``) or on its
# ``response`` (``httpx.HTTPStatusError``).
_STATUS_ATTRS = ("status", "status_code")


def _as_status(value: object) -> int | None:
    """A digit string counts: storage3 keeps Storage's ``statusCode`` as text, and a missing
    file's 404 must not read as a bug. A ``bool`` is an ``int`` but not a status."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def refused_status(exc: BaseException) -> int | None:
    """The status the dependency answered with, or ``None`` if it never answered at all."""
    for holder in (exc, getattr(exc, "response", None)):
        for attr in _STATUS_ATTRS:
            status = _as_status(getattr(holder, attr, None))
            if status is not None:
                return status
    return None


def refused_sqlstate(exc: BaseException) -> str | None:
    """The SQLSTATE Postgres answered with, on asyncpg's exception or SQLAlchemy's ``.orig``; or
    ``None`` if it never answered. Having one does not mean healthy: a lost connection is
    ``08003``, see :func:`is_refusal`.
    """
    for holder in (exc, getattr(exc, "orig", None)):
        sqlstate = getattr(holder, "sqlstate", None)
        if isinstance(sqlstate, str):
            return sqlstate
    return None


# SQLSTATE classes that are Postgres's 5xx: 08 connection_exception, 53 insufficient_resources,
# 57 operator_intervention, 58 system error, XX internal_error.
# https://www.postgresql.org/docs/current/errcodes-appendix.html
_BROKEN_SQLSTATE_CLASSES = frozenset({"08", "53", "57", "58", "XX"})


def is_refusal(exc: BaseException) -> bool:
    """A 4xx, or a SQLSTATE outside the broken classes."""
    status = refused_status(exc)
    if status is not None:
        return 400 <= status < 500
    sqlstate = refused_sqlstate(exc)
    return sqlstate is not None and sqlstate[:2] not in _BROKEN_SQLSTATE_CLASSES


def log_dependency_failure(log: Any, event: str, exc: BaseException, **context: object) -> None:
    """Log a refusal at ``info``, a breakage as an exception (an issue). ``exc`` is explicit, so
    capture works outside a live ``except`` block too."""
    if is_refusal(exc):
        log.info(event, exc_info=exc, **context)
        return
    log.exception(event, exc_info=exc, **context)
