"""Unit tests for the global handle namespace (cross-table uniqueness + reserved names)."""

import pytest

from app.shared.names import is_reserved, is_valid_handle, slugify


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


# ── handle_is_available (with fake session) ───────────────────────────────────


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def __await__(self):

        async def _inner():
            return self._value

        return _inner().__await__()


class _FakeSession:
    """Minimal async session stub: scalar() returns a preset value."""

    def __init__(self, profile_row=None, org_row=None):
        self._profile_row = profile_row
        self._org_row = org_row
        self._calls = []

    async def scalar(self, query):
        sql = str(query)
        self._calls.append(sql)
        if "profiles" in sql.lower():
            return self._profile_row
        return self._org_row


@pytest.mark.asyncio
async def test_handle_available_when_both_tables_empty():
    from app.shared.handle_service import handle_is_available

    session = _FakeSession(profile_row=None, org_row=None)
    assert await handle_is_available("alice", session)


@pytest.mark.asyncio
async def test_handle_unavailable_when_taken_by_profile():
    from app.shared.handle_service import handle_is_available

    session = _FakeSession(profile_row=object(), org_row=None)
    assert not await handle_is_available("alice", session)


@pytest.mark.asyncio
async def test_handle_unavailable_when_taken_by_org():
    from app.shared.handle_service import handle_is_available

    session = _FakeSession(profile_row=None, org_row=object())
    assert not await handle_is_available("alice", session)


@pytest.mark.asyncio
async def test_handle_unavailable_when_reserved():
    from app.shared.handle_service import handle_is_available

    session = _FakeSession(profile_row=None, org_row=None)
    assert not await handle_is_available("auth", session)
    assert not await handle_is_available("admin", session)


@pytest.mark.asyncio
async def test_unique_handle_returns_base_when_free():
    from app.shared.handle_service import unique_handle

    session = _FakeSession(profile_row=None, org_row=None)
    assert await unique_handle("alice", session) == "alice"


@pytest.mark.asyncio
async def test_unique_handle_increments_when_taken():
    from app.shared.handle_service import unique_handle

    calls = {"n": 0}

    class _CountingSession:
        async def scalar(self, query):
            sql = str(query)
            if "profiles" not in sql.lower():
                return None
            calls["n"] += 1
            # First two candidates ("alice", "alice-2") are taken; third is free.
            return object() if calls["n"] <= 2 else None

    result = await unique_handle("alice", _CountingSession())
    assert result == "alice-3"


@pytest.mark.asyncio
async def test_unique_handle_skips_reserved_base():
    from app.shared.handle_service import unique_handle

    session = _FakeSession(profile_row=None, org_row=None)
    result = await unique_handle("auth", session)
    assert result == "auth-2"
