"""The URL slug namespace: validation, reserved slugs, and uniqueness across contexts."""

import re
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

# ── Validation ────────────────────────────────────────────────────────────────

_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def is_valid_handle(handle: str) -> bool:
    return bool(_HANDLE_RE.match(handle)) and len(handle) <= 39


def validate_handle(handle: str) -> tuple[int, str] | None:
    """A handle's rejection as ``(status, message)``, or ``None`` if usable."""
    if not handle:
        return 422, "Handle cannot be empty."
    if not is_valid_handle(handle):
        return 422, "Handle must be lowercase alphanumeric with hyphens, max 39 chars."
    if is_reserved(handle):
        return 422, f"'{handle}' is a reserved name."
    return None


# ── Claimed slugs ─────────────────────────────────────────────────────────────

_reserved: set[str] = set()


def reserve(*slugs: str) -> None:
    _reserved.update(slugs)


def is_reserved(handle: str) -> bool:
    return handle in _reserved


# ── Open-list registry ────────────────────────────────────────────────────────

# ``(session, handle, exclude_id)`` → whether the handle is taken in that context.

OpenListChecker = Callable[[AsyncSession, str, uuid.UUID | None], Awaitable[bool]]

_open_lists: dict[str, OpenListChecker] = {}


def register_open_list(name: str, checker: OpenListChecker) -> None:
    _open_lists[name] = checker


async def handle_is_available(
    handle: str,
    session: AsyncSession,
    *,
    exclude_from: str | None = None,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """Neither reserved nor taken in any context. On an update, ``exclude_from`` and
    ``exclude_id`` ignore the entity being renamed."""
    if is_reserved(handle):
        return False
    for name, checker in _open_lists.items():
        xid = exclude_id if name == exclude_from else None
        if await checker(session, handle, xid):
            return False
    return True


async def unique_handle(
    base: str,
    session: AsyncSession,
    *,
    exclude_from: str | None = None,
    exclude_id: uuid.UUID | None = None,
) -> str:
    """``base``, or the first available ``base-N``."""
    candidate = base
    n = 2
    while not await handle_is_available(
        candidate, session, exclude_from=exclude_from, exclude_id=exclude_id
    ):
        candidate = f"{base}-{n}"
        n += 1
    return candidate
