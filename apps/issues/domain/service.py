"""Fingerprint and lifecycle. The fingerprint hashes the exception type and the top in-app frames
as ``file:function``, never the message, whose variable parts would split issues. A resolved issue
seen on another version than its fix regresses: git SHAs have no order, so "another" is the test.
"""

import hashlib
import traceback

from apps.issues.domain.models import IssueStatus

_IN_APP_MARKER = "/apps/"
_TOP_FRAMES = 5
_TITLE_MAX = 200
_STACK_MAX = 8000


def _normalize(filename: str) -> str:
    """A machine-independent path: from `apps/` down, or the bare filename."""
    idx = filename.rfind(_IN_APP_MARKER)
    if idx >= 0:
        return "apps/" + filename[idx + len(_IN_APP_MARKER) :]
    return filename.rsplit("/", 1)[-1]


def in_app_frames(exc: BaseException) -> list[str]:
    """The last app-owned frames as ``file:function`` (all frames when none is ours)."""
    frames = traceback.extract_tb(exc.__traceback__)
    picked = [f for f in frames if _IN_APP_MARKER in f.filename] or list(frames)
    return [f"{_normalize(f.filename)}:{f.name}" for f in picked[-_TOP_FRAMES:]]


def fingerprint(exc: BaseException, override: str | None = None) -> str:
    """``override`` replaces the computed key."""
    material = override or "|".join([type(exc).__qualname__, *in_app_frames(exc)])
    return hashlib.sha256(material.encode()).hexdigest()


def title_for(exc: BaseException) -> str:
    return f"{type(exc).__qualname__}: {exc}"[:_TITLE_MAX]


def formatted_stack(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))[-_STACK_MAX:]


def status_after_occurrence(
    current: IssueStatus, resolved_in_release: str | None, seen_version: str
) -> IssueStatus:
    """The status after one more occurrence: regressed if resolved on another version, else
    unchanged."""
    if current is IssueStatus.resolved and seen_version != (resolved_in_release or ""):
        return IssueStatus.regressed
    return current
