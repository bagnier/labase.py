"""One verdict for a failed call to something outside this process: refusal, or breakage.

Which of the two a failure is, and what each earns, is settled once (AGENTS: A broken
dependency is a bug, a refusal is not): one
verdict for GoTrue, Postgres and Storage alike, so an outage does not fill the issues screen or
stay silent depending on the module it was reached through.

An HTTP status is what tells the two apart for GoTrue and Storage, and each client library keeps
it in a place of its own — hence :func:`refused_status` rather than a table of exception classes
to maintain. Postgres has no HTTP status, but the same shape: a SQLSTATE (on the driver exception,
or on ``.orig`` where SQLAlchemy wrapped it) means the server *answered*, and most of what it can
answer — an unmigrated table, a missing grant — is ordinary, same as a 4xx. A SQLSTATE is not
itself proof of health, though: a class carrying its own failure (a lost connection, an exhausted
resource, the server's own crash or bug) is the Postgres spelling of a 5xx, and stays a bug even
though it answered. Shared cannot import a bounded context's client anyway, and would not want to:
the rule is about the *shape* of the answer, not about who answered.

Call :func:`log_dependency_failure` from the ``except`` block, passing the module's own logger —
the timeline reads a line's app off the logger that wrote it, so a failure funnelled through here
must still read as the caller's, never as ``shared``.
"""

from typing import Any

# Where the client libraries keep the status they were answered with: on the exception itself
# (gotrue's ``AuthApiError``, storage3's ``StorageException``), or on the response it wrapped
# (``httpx.HTTPStatusError``).
_STATUS_ATTRS = ("status", "status_code")


def _as_status(value: object) -> int | None:
    """One status out of whatever shape the client kept it in.

    A digit *string* counts: storage3 builds ``StorageApiError`` straight from Supabase Storage's
    JSON error body, where ``statusCode`` is text. Requiring an ``int`` read every one of those as
    "never answered", which would file each ordinary 404 — a file that isn't there — as a bug.
    ``bool`` is excluded on purpose: it is an ``int`` in Python, and ``True`` is not a status.
    """
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
    """The SQLSTATE Postgres answered with, or ``None`` if it never reached the server at all.

    Checked on the exception itself (asyncpg's own error classes) and on ``.orig`` (where
    SQLAlchemy wraps the driver exception, e.g. ``DBAPIError``) — a connection failure carries
    neither, since the server never got the chance to answer. A connection *lost* mid-operation
    does carry one (asyncpg's ``ConnectionDoesNotExistError`` is ``08003``), which is why this is
    only "did it answer", never by itself "is it healthy" — :func:`is_refusal` still has to weigh
    the class.
    """
    for holder in (exc, getattr(exc, "orig", None)):
        sqlstate = getattr(holder, "sqlstate", None)
        if isinstance(sqlstate, str):
            return sqlstate
    return None


# SQLSTATE classes (the code's first two characters) where Postgres answered but the answer is
# the server breaking, not the caller's mistake — the Postgres spelling of a 5xx: 08
# connection_exception, 53 insufficient_resources, 57 operator_intervention, 58 (external) system
# error, XX internal_error. https://www.postgresql.org/docs/current/errcodes-appendix.html
_BROKEN_SQLSTATE_CLASSES = frozenset({"08", "53", "57", "58", "XX"})


def is_refusal(exc: BaseException) -> bool:
    """Whether the dependency answered *no* — a 4xx, or a Postgres SQLSTATE outside the classes
    where Postgres itself is what broke — an outcome, not a defect."""
    status = refused_status(exc)
    if status is not None:
        return 400 <= status < 500
    sqlstate = refused_sqlstate(exc)
    return sqlstate is not None and sqlstate[:2] not in _BROKEN_SQLSTATE_CLASSES


def log_dependency_failure(log: Any, event: str, exc: BaseException, **context: object) -> None:
    """Record a failed call to a dependency at the level its nature warrants.

    ``exc`` is passed to the line explicitly rather than resolved from the frame, so the capture
    seam holds wherever this is called from and not only from inside a live ``except`` block —
    the same lesson the 500 handler learned.
    """
    if is_refusal(exc):
        # At ``info`` the seam never fires, so the stack reaches the log sink and opens nothing —
        # a refusal is an ordinary outcome, and still the only description of which one it was.
        log.info(event, exc_info=exc, **context)
        return
    log.exception(event, exc_info=exc, **context)
