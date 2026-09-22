"""`walk` must page through every object of a folder, not just the API's default page."""

from collections.abc import Sequence
from typing import Any

import pytest

from scripts.backup_storage import walk

_PAGE_SIZE = 100


class _FakeStore:
    """Mimics storage3's ``list()``: a single level, capped at ``_PAGE_SIZE`` unless paged."""

    def __init__(self, names_by_prefix: dict[str, Sequence[str]]):
        self._names_by_prefix = names_by_prefix

    async def list(
        self, prefix: str = "", options: dict[str, Any] | None = None
    ) -> Sequence[dict[str, Any]]:
        options = options or {}
        limit = options.get("limit", _PAGE_SIZE)
        offset = options.get("offset", 0)
        names = self._names_by_prefix.get(prefix, [])
        return [{"name": n, "id": "obj"} for n in names[offset : offset + limit]]


@pytest.mark.asyncio
async def test_a_folder_of_more_than_one_page_is_walked_in_full():
    names = [f"file-{i}" for i in range(_PAGE_SIZE + 36)]
    store = _FakeStore({"": names})

    paths = await walk(store, "")

    assert sorted(paths) == sorted(names)
