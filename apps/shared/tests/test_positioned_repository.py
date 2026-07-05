from types import SimpleNamespace

from apps.shared.persistence.repository import PositionedRepository


class _ByPk(PositionedRepository):
    position_key = "id"


class _ByPageId(PositionedRepository):
    position_key = "page_id"


def _items(key: str, *keys: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(**{key: k, "position": pos}) for pos, k in enumerate(keys)]


def _keys(key: str, ordered: list[SimpleNamespace]) -> list[str]:
    return [getattr(i, key) for i in ordered]


def test_reorder_moves_item_above_target():
    ordered = _ByPk._reorder(_items("id", "a", "b", "c"), "c", "a")
    assert ordered is not None
    assert _keys("id", ordered) == ["c", "a", "b"]


def test_reorder_moves_item_to_end_when_above_is_none():
    ordered = _ByPk._reorder(_items("id", "a", "b", "c"), "a", None)
    assert ordered is not None
    assert _keys("id", ordered) == ["b", "c", "a"]


def test_reorder_returns_none_for_unknown_item():
    assert _ByPk._reorder(_items("id", "a", "b"), "ghost", "a") is None


def test_reorder_returns_none_for_unknown_target():
    assert _ByPk._reorder(_items("id", "a", "b"), "a", "ghost") is None


def test_reorder_honors_custom_position_key():
    ordered = _ByPageId._reorder(_items("page_id", "p1", "p2", "p3"), "p3", "p1")
    assert ordered is not None
    assert _keys("page_id", ordered) == ["p3", "p1", "p2"]
