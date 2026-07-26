"""BusinessEvent vocabulary + the bus/persist wiring that records it.

Covers the two mechanisms Phase 1 introduced: CRUD ``kind`` derivation (so apps write no dotted
strings) and MRO dispatch (so one subscriber on the base records every subclass), plus the
non-blocking persist contract (``emit`` never waits on — or fails from — the DB write).
"""

import uuid
from dataclasses import dataclass

import pytest

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated
from apps.shared.events.bus import EventBus
from apps.shared.events.registry import EventRegistry, registry
from apps.shared.events.repository import event_to_log


class WidgetEvent(BusinessEvent):
    entity = "widget"
    icon = "cube"


@dataclass(frozen=True, kw_only=True)
class WidgetCreated(WidgetEvent, EntityCreated):
    pass


@dataclass(frozen=True, kw_only=True)
class WidgetUpdated(WidgetEvent, EntityUpdated):
    pass


@dataclass(frozen=True, kw_only=True)
class WidgetDeleted(WidgetEvent, EntityDeleted):
    pass


def test_crud_kind_is_derived_from_entity_and_verb():
    assert WidgetCreated.kind == "widget.created"
    assert WidgetUpdated.kind == "widget.updated"
    assert WidgetDeleted.kind == "widget.deleted"
    # The per-app mixin's icon rides on every concrete event; level defaults to info.
    assert WidgetCreated.icon == "cube"
    assert WidgetCreated.level == "info"


def test_explicit_kind_wins_over_derivation():
    @dataclass(frozen=True, kw_only=True)
    class SignedIn(BusinessEvent):
        kind = "auth.signed_in"

    assert SignedIn.kind == "auth.signed_in"


def test_concrete_events_register_in_the_catalog_for_reconstruction():
    # The listener rebuilds a typed event from a persisted row's `kind`, so every concrete event
    # registers itself in the registry's catalog. Abstract bases (empty kind) do not.
    assert registry.event_class_for("widget.created") is WidgetCreated
    assert registry.event_class_for("widget.deleted") is WidgetDeleted
    assert registry.event_class_for("no.such_kind") is None


@pytest.mark.asyncio
async def test_emit_does_not_run_handlers_in_process():
    # emit only persists the fact — every reaction (`on` consumers, `spread` handlers) runs in the
    # listener off the trail, never here. A spread handler registered on this bus stays inert.
    bus = EventBus(EventRegistry())
    seen: list[object] = []

    @dataclass(frozen=True, kw_only=True)
    class ConfigChanged(BusinessEvent):
        kind = "config.changed"

    async def reload(event: ConfigChanged) -> None:
        seen.append(event)

    bus.registry.declare_events("config", ConfigChanged)  # emit refuses an undeclared event
    bus.spread(ConfigChanged, reload)

    await bus.emit(ConfigChanged())
    assert seen == []  # emit does not run spread handlers in-process


def test_event_to_log_lifts_scoping_and_carries_metadata():
    # emit maps a BusinessEvent straight onto a business_events row: scoping to columns, rest to
    # payload — a single event → row hop, no intermediate column dict.
    actor, org, eid = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    row = event_to_log(WidgetCreated(user_id=actor, org_id=org, entity_id=eid, entity_name="Gizmo"))
    assert row.kind == "widget.created"
    assert row.icon == "cube"
    assert row.user_id == actor
    assert row.org_id == org
    assert row.entity_id == eid  # the concerned entity's uuid, lifted to its own column
    # scoping fields are lifted to columns, never duplicated into the payload
    payload = row.payload
    assert payload is not None
    assert payload["entity_name"] == "Gizmo"
    assert "user_id" not in payload
    assert "org_id" not in payload
    assert "entity_id" not in payload


# ── The UUID-aware serializer socle: DTOs carry uuid.UUID, the edge stringifies/re-parses ──────


@dataclass(frozen=True, kw_only=True)
class _RefEvent(BusinessEvent):
    kind = "test_ref.happened"
    ref_id: uuid.UUID | None = None  # a plain FK carried as uuid on the DTO
    token: uuid.UUID | None = None  # name triggers redaction — never reaches json.dumps


def test_event_to_log_stringifies_uuid_payload_fields():
    # A uuid.UUID payload field must reach the JSONB column json-safe (stdlib json can't dump UUID).
    ref = uuid.uuid7()
    row = event_to_log(_RefEvent(user_id=uuid.uuid7(), ref_id=ref))
    assert row.payload is not None
    assert row.payload["ref_id"] == str(ref)  # stringified at the one serialization edge
    assert row.payload["token"] is None  # None stays None (redaction only masks a set value)


def test_event_to_log_lifts_a_uuid_entity_id():
    # entity_id is the entity's uuid pk, lifted straight to its own uuid column — no str() edge.
    eid = uuid.uuid7()
    row = event_to_log(WidgetCreated(entity_id=eid, entity_name="Gizmo"))
    assert row.entity_id == eid


def test_from_payload_reparses_every_uuid_field_by_type():
    # The round-trip through the queue serializes every uuid to a string; from_payload re-parses any
    # field annotated uuid.UUID back — generically, not from a hardcoded list.
    ref, actor = uuid.uuid7(), uuid.uuid7()
    event = _RefEvent.from_payload({"ref_id": str(ref), "user_id": str(actor)})
    assert event.ref_id == ref
    assert event.user_id == actor


def test_from_payload_is_defensive_on_unparseable_strings():
    # A redacted token ("***") is annotated uuid.UUID but not a valid uuid — leave it untouched
    # rather than crash the reconstruction.
    event = _RefEvent.from_payload({"token": "***"})
    assert event.token == "***"


def test_from_payload_reparses_a_uuid_entity_id():
    # entity_id round-trips through the queue as a string and is re-parsed back to its uuid pk.
    eid = uuid.uuid7()
    event = _RefEvent.from_payload({"entity_id": str(eid)})
    assert event.entity_id == eid
