"""One verdict for a failed call out of the process: a refusal or a breakage
(AGENTS: a broken dependency is a bug, a refusal is not).

Only a 4xx is a refusal. GoTrue and Storage answer with an HTTP status; a SQLSTATE never is one,
since every SQL the verdict sees is ours and a wrong one is our bug. The verdict reads the shape
of the answer, not the client class, which ``apps.shared`` could not import anyway.

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


def is_refusal(exc: BaseException) -> bool:
    """Whether the dependency answered *no* — a 4xx, which is an outcome and not a defect."""
    status = refused_status(exc)
    return status is not None and 400 <= status < 500


def log_dependency_failure(log: Any, event: str, exc: BaseException, **context: object) -> None:
    """Log a refusal at ``info``, a breakage as an exception (an issue). ``exc`` is explicit, so
    capture works outside a live ``except`` block too."""
    if is_refusal(exc):
        log.info(event, exc_info=exc, **context)
        return
    log.exception(event, exc_info=exc, **context)
