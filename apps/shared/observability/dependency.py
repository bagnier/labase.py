"""One verdict for a failed call to something outside this process: refusal, or breakage.

The base reaches four dependencies — GoTrue, Postgres, Storage, SMTP — and every call to one of
them can fail two ways that look alike in an ``except`` block and mean opposite things:

- **It answered no.** A wrong password, an expired confirmation link, a rate limit, a row that
  isn't there. The dependency did its job; the outcome is ordinary, and belongs at ``info``.
- **It is broken.** Unreachable, a 5xx, a client library raising something of its own. Nothing
  about the request explains it, nobody is coming to fix it on their own, and the capture seam
  turns it into an issue.

An HTTP status is what tells the two apart, and each client library keeps it in a place of its
own — hence :func:`refused_status` rather than a table of exception classes to maintain. Shared
cannot import a bounded context's client anyway, and would not want to: the rule is about the
*shape* of the answer, not about who answered.

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


def is_refusal(exc: BaseException) -> bool:
    """Whether the dependency answered *no* — a 4xx, which is an outcome and not a defect."""
    status = refused_status(exc)
    return status is not None and 400 <= status < 500


def log_dependency_failure(log: Any, event: str, exc: BaseException, **context: object) -> None:
    """Record a failed call to a dependency at the level its nature warrants.

    ``exc`` is passed to the line explicitly rather than resolved from the frame, so the capture
    seam holds wherever this is called from and not only from inside a live ``except`` block —
    the same lesson the 500 handler learned.
    """
    if is_refusal(exc):
        log.info(event, **context)
        return
    log.exception(event, exc_info=exc, **context)
