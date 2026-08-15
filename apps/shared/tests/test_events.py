"""BusinessEvent vocabulary + the bus/persist wiring that records it.

Covers the two mechanisms Phase 1 introduced: CRUD ``kind`` derivation (so apps write no dotted
strings) and MRO dispatch (so one subscriber on the base records every subclass), plus the
non-blocking persist contract (``emit`` never waits on — or fails from — the DB write).
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import pytest

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated, OrgScoped
from apps.shared.events.bus import EventBus
from apps.shared.events.registry import EventRegistry, registry
from apps.shared.events.repository import (
    LIFTED_COLUMNS,
    TRAIL_COLUMNS,
    TrailRow,
    event_to_log,
    task_payload,
)
from apps.shared.events.types import _is_secret_field_name


class WidgetEvent(OrgScoped, BusinessEvent):
    app_name = "widget"
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
    # The per-app mixin's icon rides on every concrete event.
    assert WidgetCreated.icon == "cube"


def test_a_non_crud_event_still_derives_its_kind_from_its_own_verb():
    # Non-CRUD actions spell out a verb of their own rather than a dotted string: the derivation is
    # unconditional, because the trail composes kind the very same way (a generated column). A
    # hand-written kind could only make the class disagree with the rows it is meant to rebuild.
    @dataclass(frozen=True, kw_only=True)
    class SignedIn(BusinessEvent):
        app_name = "test_explicit"
        verb = "signed_in"

    assert SignedIn.kind == "test_explicit.signed_in"


def test_an_event_naming_only_one_half_has_no_kind_and_stays_out_of_the_catalog():
    # Both halves or nothing: an abstract base (an app mixin with no verb) is not a fact, so it
    # never claims a kind and never enters the catalog the listener rebuilds from.
    class HalfNamed(BusinessEvent):
        app_name = "test_half"

    assert HalfNamed.kind == ""
    assert registry.event_class_for("") is None


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
        app_name = "config"
        verb = "changed"

    async def reload(event: ConfigChanged) -> None:
        seen.append(event)

    bus.registry.declare_events(ConfigChanged)  # emit refuses an undeclared event
    bus.spread(ConfigChanged, reload)

    await bus.emit(ConfigChanged())
    assert seen == []  # emit does not run spread handlers in-process


def test_event_to_log_lifts_scoping_and_carries_metadata():
    # emit maps a BusinessEvent straight onto a business_events row: scoping to columns, rest to
    # payload — a single event → row hop, no intermediate column dict.
    actor, org, eid = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    row = event_to_log(WidgetCreated(user_id=actor, org_id=org, entity_id=eid, entity_name="Gizmo"))
    # The row carries the two halves; `kind` is generated from them in the DB, so it has no value
    # on a row that hasn't been written yet — the composition lives there, not here.
    assert (row.app_name, row.verb) == ("widget", "created")
    assert row.icon == "cube"
    assert row.user_id == actor
    assert row.org_id == org
    assert row.entity_id == eid  # the concerned entity's uuid, lifted to its own column
    # scoping fields are lifted to columns, never duplicated into the payload
    assert row.entity_name == "Gizmo"  # the subject's name: its own column, pinned at write time
    payload = row.payload
    assert payload is not None
    assert "entity_name" not in payload
    assert "user_id" not in payload
    assert "org_id" not in payload
    assert "entity_id" not in payload


# ── One serialized shape, closed by a round-trip ───────────────────────────────────────────────
#
# A fact crosses the persistence/delivery boundary through four field lists that must agree: the
# columns `event_to_log` lifts out of the payload, the columns the delivery scans SELECT, the
# `TrailRow` they land in, and the keys `task_payload` folds back before `from_payload` rebuilds
# the event. These tests fix that agreement, so a base field added to `BusinessEvent` without
# threading it through the whole chain fails here, loudly, not by vanishing between write and read.


@dataclass(frozen=True, kw_only=True)
class _NoteEvent(BusinessEvent):
    app_name = "test_note"
    verb = "noted"
    note: str | None = None  # a plain string riding in the payload
    ref_id: uuid.UUID | None = None  # a uuid FK riding in the payload (stringified at the edge)


def _reconstruct_through_delivery(event: BusinessEvent) -> BusinessEvent:
    """Drive an event through the real serialized chain without a DB: `event_to_log` builds the row,
    we project exactly the columns the delivery scans read (`TRAIL_COLUMNS`) off it — computing the
    generated `kind`, which a SELECT returns but an unflushed ORM row leaves unset — then
    `task_payload` + `from_payload` rebuild it, exactly as the listener does off a claimed row."""
    row = event_to_log(event)
    projected = {c: getattr(row, c) for c in TRAIL_COLUMNS}
    projected["kind"] = f"{row.app_name}.{row.verb}"  # the generated column, unset pre-flush
    trail = cast(TrailRow, projected)
    return type(event).from_payload(task_payload(trail))


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(
            WidgetCreated(
                user_id=uuid.uuid7(),
                org_id=uuid.uuid7(),
                entity_id=uuid.uuid7(),
                entity_name="Gizmo",
            ),
            id="org-scoped-named",
        ),
        pytest.param(_NoteEvent(user_id=uuid.uuid7()), id="server-wide-actor-only"),
        pytest.param(
            _NoteEvent(user_id=uuid.uuid7(), ref_id=uuid.uuid7()), id="uuid-payload-field"
        ),
        pytest.param(
            _NoteEvent(
                user_id=uuid.uuid7(), entity_id=uuid.uuid7(), entity_name="Report", note="hi"
            ),
            id="named-subject-with-payload",
        ),
    ],
)
def test_a_fact_round_trips_identically_through_the_serialized_chain(event: BusinessEvent):
    # event → row → TrailRow → payload → event returns something equal to what went in. Frozen
    # dataclass equality compares every instance field, so this asserts the whole event survives.
    assert _reconstruct_through_delivery(event) == event


def test_the_delivery_column_lists_derive_from_one_source():
    # The lifted columns, the SELECT columns and the TrailRow that receives them are three views of
    # one tuple — not three hand-kept lists that must be edited in lockstep. Pin them to it so a
    # drift (a column added to one but not the others) fails at import of this test, not in prod.
    correlation = {"id", "kind", "created_at", "request_id"}  # row identity + delivery context
    assert set(TRAIL_COLUMNS) == correlation | set(LIFTED_COLUMNS) | {"payload"}
    assert set(TrailRow.__annotations__) == set(TRAIL_COLUMNS)


# ── C4: the write path goes through the SECURITY DEFINER writer function, not a raw INSERT ──────


@pytest.mark.asyncio
async def test_the_write_path_calls_the_definer_function_with_the_row_columns():
    # Since C4 revoked the raw INSERT grant, the trail is written only through
    # record_business_event(...). Assert the write path calls exactly that, with the row's columns
    # as arguments and the payload json-encoded for the jsonb parameter — no ORM INSERT.
    from sqlalchemy.ext.asyncio import AsyncSession

    from apps.shared.events.models import BusinessEventRecord
    from apps.shared.events.repository._write import _RECORD, _record_row

    captured: dict[str, object] = {}

    class _FakeSession:
        async def execute(self, statement: object, params: object = None) -> None:
            captured["statement"] = statement
            captured["params"] = params

    row = BusinessEventRecord(
        app_name="todo", verb="created", icon="check", user_id=uuid.uuid7(), payload={"k": "v"}
    )
    await _record_row(cast(AsyncSession, _FakeSession()), row)

    assert captured["statement"] is _RECORD  # the writer function, not an ORM INSERT
    params = cast(dict, captured["params"])
    assert (params["app_name"], params["verb"], params["icon"]) == ("todo", "created", "check")
    assert params["user_id"] == row.user_id
    assert params["payload"] == json.dumps({"k": "v"})  # json-encoded for the jsonb arg


# ── C2: a delivered event is self-descriptive (its own instant) and correlated (the request) ───


def _trail_row(**over: object) -> TrailRow:
    """A TrailRow with every column present, overridable — the shape a delivery scan returns."""
    row: dict[str, object] = {
        "id": uuid.uuid7(),
        "kind": "test_note.noted",
        "created_at": None,
        "request_id": None,
        "user_id": None,
        "org_id": None,
        "entity_id": None,
        "entity_name": None,
        "payload": {},
    }
    row.update(over)
    return cast(TrailRow, row)


def test_task_payload_folds_the_fact_instant_and_the_originating_request():
    # created_at and request_id live in their own columns; delivery folds them into the payload as
    # json-safe strings (iso / str) so they survive the queue, alongside the dedup event_id.
    fid, rid = uuid.uuid7(), uuid.uuid7()
    instant = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    row = _trail_row(id=fid, created_at=instant, request_id=rid, payload={"note": "hi"})
    payload = task_payload(row)
    assert payload["created_at"] == instant.isoformat()
    assert payload["request_id"] == str(rid)
    assert payload["event_id"] == str(fid)
    assert payload["note"] == "hi"


def test_a_delivered_event_carries_the_facts_instant_rebuilt_from_the_row():
    # The plan's promise: a durable consumer receives an event whose instant is the fact's, so it
    # reasons about when the fact happened — not when a retry/park finally delivered it.
    instant = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    event = _NoteEvent.from_payload({"note": "hi", "created_at": instant.isoformat()})
    assert event.created_at == instant


def test_the_emitted_event_has_no_instant_because_the_trail_is_the_clock():
    # The emitter never stamps created_at (one clock: the trail's own column assigns it). It is None
    # on the emitted event and populated only on the reconstructed one a consumer receives.
    assert _NoteEvent(user_id=uuid.uuid7()).created_at is None


def test_request_id_rides_to_the_log_context_not_onto_the_event():
    # request_id correlates the reaction's *logs* with the emitting request; it is not an event
    # field, so from_payload drops it rather than turning it into event state.
    event = _NoteEvent.from_payload({"request_id": str(uuid.uuid7()), "note": "x"})
    assert not hasattr(event, "request_id")


# ── The UUID-aware serializer socle: DTOs carry uuid.UUID, the edge stringifies/re-parses ──────


@dataclass(frozen=True, kw_only=True)
class _RefEvent(BusinessEvent):
    app_name = "test_ref"
    verb = "happened"
    ref_id: uuid.UUID | None = None  # a plain FK carried as uuid on the DTO


def test_event_to_log_stringifies_uuid_payload_fields():
    # A uuid.UUID payload field must reach the JSONB column json-safe (stdlib json can't dump UUID).
    ref = uuid.uuid7()
    row = event_to_log(_RefEvent(user_id=uuid.uuid7(), ref_id=ref))
    assert row.payload is not None
    assert row.payload["ref_id"] == str(ref)  # stringified at the one serialization edge


def test_event_to_log_lifts_a_uuid_entity_id():
    # entity_id is the entity's uuid pk, lifted straight to its own uuid column — no str() edge.
    eid = uuid.uuid7()
    row = event_to_log(WidgetCreated(org_id=uuid.uuid7(), entity_id=eid, entity_name="Gizmo"))
    assert row.entity_id == eid


def test_from_payload_reparses_every_uuid_field_by_type():
    # The round-trip through the queue serializes every uuid to a string; from_payload re-parses any
    # field annotated uuid.UUID back — generically, not from a hardcoded list.
    ref, actor = uuid.uuid7(), uuid.uuid7()
    event = _RefEvent.from_payload({"ref_id": str(ref), "user_id": str(actor)})
    assert event.ref_id == ref
    assert event.user_id == actor


def test_from_payload_is_defensive_on_unparseable_strings():
    # A stored value that isn't a valid uuid (a hand-inserted row, a legacy shape) is left untouched
    # rather than crashing the rebuild — the listener's guard decides what to do with the odd event.
    event = _RefEvent.from_payload({"ref_id": "not-a-uuid"})
    assert event.ref_id == "not-a-uuid"


# ── C3: a secret cannot enter a fact ───────────────────────────────────────────────────────────


def test_a_secret_named_field_is_refused_at_class_definition():
    # The trail is immutable, kept indefinitely, RLS-readable by an org's members and exportable —
    # a secret has no business there. Declaring one is refused at class creation (before @dataclass
    # even applies), and the message names the alternative: carry the subject's id, re-read state.
    with pytest.raises(TypeError, match="secret material") as exc:

        @dataclass(frozen=True, kw_only=True)
        class Leaky(BusinessEvent):
            app_name = "test_secret"
            verb = "leaked"
            api_key: str | None = None

    assert "api_key_id" in str(exc.value)  # points to carrying the pk instead


@pytest.mark.parametrize(
    "field_name",
    ["access_token", "recovery_code", "otp_secret", "jwt", "credential", "user_password"],
)
def test_secret_material_is_refused_whatever_the_spelling(field_name: str):
    # The denylist is broader than the three old substrings and underscore-insensitive, so no
    # spelling of a secret slips through as an event field.
    with pytest.raises(TypeError, match="secret material"):
        type(
            "Leaky",
            (BusinessEvent,),
            {"__annotations__": {field_name: str}, field_name: None, "app_name": "x", "verb": "y"},
        )


def test_an_id_reference_to_a_secret_bearing_entity_is_allowed():
    # The recommended alternative must itself be legal: an event may carry the *pk* of a
    # secret-bearing entity (api_key_id) — that is a correlation id, not the secret.
    @dataclass(frozen=True, kw_only=True)
    class Rotated(BusinessEvent):
        app_name = "test_secret"
        verb = "rotated"
        api_key_id: uuid.UUID | None = None

    assert Rotated.kind == "test_secret.rotated"


def test_is_secret_field_name_carves_out_id_references():
    assert _is_secret_field_name("api_key") is True
    assert _is_secret_field_name("access_token") is True
    assert _is_secret_field_name("recovery_code") is True
    assert _is_secret_field_name("api_key_id") is False  # the pk of the secret-bearing entity
    assert _is_secret_field_name("entity_id") is False
    assert _is_secret_field_name("title") is False


def test_from_payload_refuses_a_stored_null_for_a_required_field():
    # A trail row whose org column is NULL cannot rebuild an org-scoped fact. Dataclasses don't
    # validate at runtime, so without this the event would come back claiming `org_id=None` while
    # its type promises a uuid — a lie handed to a consumer. Refusing is what makes the listener's
    # guard skip the row (and log it) instead of acting on it.
    with pytest.raises(TypeError):
        WidgetCreated.from_payload({"org_id": None, "entity_id": str(uuid.uuid7())})


def test_from_payload_still_accepts_a_stored_null_for_an_optional_field():
    # The converse: absence is legitimate where the type allows it — a server-wide fact has no
    # actor, and that must keep rebuilding fine.
    event = _RefEvent.from_payload({"user_id": None, "ref_id": None})
    assert event.user_id is None


def test_from_payload_reparses_a_uuid_entity_id():
    # entity_id round-trips through the queue as a string and is re-parsed back to its uuid pk.
    eid = uuid.uuid7()
    event = _RefEvent.from_payload({"entity_id": str(eid)})
    assert event.entity_id == eid


def test_two_classes_cannot_claim_the_same_kind():
    """A kind is the trail's stored identity, so it must map back to exactly one class.

    The catalog is keyed by kind and was last-write-wins: a second claimant silently replaced the
    first, and the listener then handed the *wrong* type to that kind's durable consumers. This bit
    us for real — a fixture declaring "auth.signed_in" displaced the shipped event process-wide.
    """

    @dataclass(frozen=True, kw_only=True)
    class First(BusinessEvent):
        app_name = "test_dup"
        verb = "happened"

    with pytest.raises(ValueError, match=r"test_dup\.happened"):

        @dataclass(frozen=True, kw_only=True)
        class Second(BusinessEvent):
            app_name = "test_dup"
            verb = "happened"


def test_redeclaring_the_same_class_stays_idempotent():
    """A module reimported — or a class defined in a test body that runs twice — re-creates the
    same declaration. That must not trip the guard, so it compares where a class is declared
    rather than object identity."""

    def declare() -> type[BusinessEvent]:
        @dataclass(frozen=True, kw_only=True)
        class Same(BusinessEvent):
            app_name = "test_dup"
            verb = "redeclared"

        return Same

    declare()
    declare()  # same module and qualname: allowed
