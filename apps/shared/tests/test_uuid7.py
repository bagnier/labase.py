"""Guard: primary keys must stay time-ordered (UUIDv7), not random (UUIDv4).

The append-only stores lean on the pk being monotonic — the event listener claims/scans by
``business_events.id`` and the issues detail page pages by ``error_events.id`` (``id desc`` /
``id < before_id``). A silent revert of the ``UUIDPk`` default to ``uuid.uuid4`` would keep every
type check and most tests green while quietly breaking that ordering. These assertions fail loudly
instead — one on the mixin every model inherits, one on the primitive itself.
"""

import uuid

from apps.shared.persistence.base import UUIDPk


def test_uuidpk_column_default_generates_a_v7_uuid():
    # The callable SQLAlchemy fires for a new pk (wrapped to take an execution context it ignores).
    factory = UUIDPk.__dict__["id"].column.default.arg
    generated = factory(None)
    assert isinstance(generated, uuid.UUID)
    assert generated.version == 7  # 4 here would mean the default reverted to random uuids


def test_uuid7_is_time_ordered_and_versioned():
    ids = [uuid.uuid7() for _ in range(50)]
    assert all(i.version == 7 for i in ids)
    # UUIDv7 sorts chronologically by generation, so a byte-wise sort preserves insertion order.
    assert [str(i) for i in ids] == sorted(str(i) for i in ids)
