"""Primary keys stay time-ordered: the listener's cursor and the occurrence pages rely on it, and
a revert to uuid4 would pass the type check and most tests."""

import uuid

from apps.shared.persistence.base import UUIDPk


def test_uuidpk_column_default_generates_a_v7_uuid():
    factory = UUIDPk.__dict__["id"].column.default.arg
    generated = factory(None)
    assert isinstance(generated, uuid.UUID)
    assert generated.version == 7


def test_uuid7_is_time_ordered_and_versioned():
    ids = [uuid.uuid7() for _ in range(50)]
    assert all(i.version == 7 for i in ids)
    assert [str(i) for i in ids] == sorted(str(i) for i in ids)
