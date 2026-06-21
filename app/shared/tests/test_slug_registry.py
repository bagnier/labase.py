"""Unit tests for the global handle namespace (cross-table uniqueness + reserved names)."""

import contextlib
import uuid
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared import slug_registry as _svc
from app.shared.slug_registry import is_reserved, is_valid_handle, slugify

_SESSION: AsyncSession = cast(AsyncSession, object())  # fake session; checkers never use it


@pytest.fixture(scope="module", autouse=True)
def _wire_reserved_slugs():
    """Reserved slugs are claimed at composition: importing app.main wires every context."""
    import app.main

    assert app.main.app is not None


# ── slugify ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value, expected",
    [
        ("alice", "alice"),
        ("Alice Wonderland", "alice-wonderland"),
        ("hello.world@example.com", "hello-world-example-com"),
        ("  spaces  ", "spaces"),
        ("über-cool", "ber-cool"),
        ("123abc", "123abc"),
        ("a--b", "a-b"),
    ],
)
def test_slugify(value, expected):
    assert slugify(value) == expected


# ── is_valid_handle ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "handle",
    ["a", "alice", "alice-wonder", "abc123", "1start", "a" * 39],
)
def test_valid_handles(handle):
    assert is_valid_handle(handle)


@pytest.mark.parametrize(
    "handle",
    [
        "",
        "-starts-with-dash",
        "HAS_UPPER",
        "has space",
        "dot.inside",
        "a" * 40,
    ],
)
def test_invalid_handles(handle):
    assert not is_valid_handle(handle)


# ── is_reserved ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["auth", "login", "admin", "profile", "console", "static"])
def test_reserved_names_are_reserved(name):
    assert is_reserved(name)


def test_non_reserved_names_are_not_reserved():
    assert not is_reserved("alice")
    assert not is_reserved("myorg")


# ── handle_is_available / unique_handle ──────────────────────────────────────
#
# The service uses a module-level registry (_open_lists). Tests inject fake
# checkers directly into that dict and restore it after each test.


@contextlib.contextmanager
def _fake_registry(**namespaces):
    """Temporarily replace _open_lists with the given fake checkers."""
    original = _svc._open_lists.copy()
    _svc._open_lists.clear()
    _svc._open_lists.update(namespaces)
    try:
        yield
    finally:
        _svc._open_lists.clear()
        _svc._open_lists.update(original)


def _checker(taken: bool):
    return AsyncMock(return_value=taken)


@pytest.mark.asyncio
async def test_handle_available_when_both_tables_empty():
    session = _SESSION
    with _fake_registry(profiles=_checker(False), organizations=_checker(False)):
        assert await _svc.handle_is_available("alice", session)


@pytest.mark.asyncio
async def test_handle_unavailable_when_taken_by_profile():
    session = _SESSION
    with _fake_registry(profiles=_checker(True), organizations=_checker(False)):
        assert not await _svc.handle_is_available("alice", session)


@pytest.mark.asyncio
async def test_handle_unavailable_when_taken_by_org():
    session = _SESSION
    with _fake_registry(profiles=_checker(False), organizations=_checker(True)):
        assert not await _svc.handle_is_available("alice", session)


@pytest.mark.asyncio
async def test_handle_unavailable_when_reserved():
    session = _SESSION
    with _fake_registry(profiles=_checker(False), organizations=_checker(False)):
        assert not await _svc.handle_is_available("auth", session)
        assert not await _svc.handle_is_available("admin", session)


@pytest.mark.asyncio
async def test_unique_handle_returns_base_when_free():
    session = _SESSION
    with _fake_registry(profiles=_checker(False), organizations=_checker(False)):
        assert await _svc.unique_handle("alice", session) == "alice"


@pytest.mark.asyncio
async def test_unique_handle_increments_when_taken():
    session = _SESSION
    calls = {"n": 0}

    async def _counting(sess, handle, exclude_id=None):
        calls["n"] += 1
        return calls["n"] <= 2  # "alice" and "alice-2" are taken; "alice-3" is free

    with _fake_registry(profiles=_counting, organizations=_checker(False)):
        assert await _svc.unique_handle("alice", session) == "alice-3"


@pytest.mark.asyncio
async def test_unique_handle_skips_reserved_base():
    session = _SESSION
    with _fake_registry(profiles=_checker(False), organizations=_checker(False)):
        assert await _svc.unique_handle("auth", session) == "auth-2"


@pytest.mark.asyncio
async def test_exclude_from_skips_own_namespace():
    """exclude_from passes exclude_id only to the named namespace, not others."""
    session = _SESSION
    own_id = uuid.uuid4()
    received: dict = {}

    async def _profile_checker(sess, handle, exclude_id=None):
        received["profile_exclude"] = exclude_id
        return False

    async def _org_checker(sess, handle, exclude_id=None):
        received["org_exclude"] = exclude_id
        return False

    with _fake_registry(profiles=_profile_checker, organizations=_org_checker):
        await _svc.handle_is_available("alice", session, exclude_from="profiles", exclude_id=own_id)

    assert received["profile_exclude"] == own_id
    assert received["org_exclude"] is None
