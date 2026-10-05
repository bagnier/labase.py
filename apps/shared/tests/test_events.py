"""``BusinessEvent``: ``kind`` derivation, the secret-field refusal, and the round trip
``event_to_record`` → ``task_payload`` → ``from_payload``."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated, OrgScoped
from apps.shared.events.bus import EventBus
from apps.shared.events.catalog import catalog
from apps.shared.events.models import BusinessEventRecord
from apps.shared.events.repository import (
    _RECORD,
    LIFTED_COLUMNS,
    _append_record,
    event_to_record,
    task_payload,
)
from apps.shared.events.types import _is_secret_field_name
from apps.shared.events.wiring import EventWiring


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
    assert WidgetCreated.icon == "cube"


def test_a_non_crud_event_still_derives_its_kind_from_its_own_verb():
    @dataclass(frozen=True, kw_only=True)
    class SignedIn(BusinessEvent):
        app_name = "test_explicit"
        verb = "signed_in"

    assert SignedIn.kind == "test_explicit.signed_in"


def test_an_event_naming_only_one_half_has_no_kind_and_stays_out_of_the_catalog():
    class HalfNamed(BusinessEvent):
        app_name = "test_half"

    assert HalfNamed.kind == ""
    assert catalog.class_for("") is None


def test_concrete_events_register_in_the_catalog_for_reconstruction():
    assert catalog.class_for("widget.created") is WidgetCreated
    assert catalog.class_for("widget.deleted") is WidgetDeleted
    assert catalog.class_for("no.such_kind") is None


@pytest.mark.asyncio
async def test_emit_does_not_run_handlers_in_process():
    own = EventWiring()
    bus = EventBus(own)
    seen: list[object] = []

    @dataclass(frozen=True, kw_only=True)
    class ConfigChanged(BusinessEvent):
        app_name = "config"
        verb = "changed"

    async def reload(event: ConfigChanged) -> None:
        seen.append(event)

    own.declare(ConfigChanged)
    bus.spread(ConfigChanged, reload)

    with patch("apps.shared.events.bus.EventRepository", return_value=AsyncMock()):
        await bus.emit(ConfigChanged(), cast(AsyncSession, None))

    assert seen == []


def test_event_to_record_lifts_scoping_and_carries_metadata():
    actor, org, eid = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    record = event_to_record(
        WidgetCreated(user_id=actor, org_id=org, entity_id=eid, entity_name="Gizmo")
    )
    # Not `kind`: the database generates it.
    assert (record.app_name, record.verb) == ("widget", "created")
    assert record.icon == "cube"
    assert record.user_id == actor
    assert record.org_id == org
    assert record.entity_id == eid
    assert record.entity_name == "Gizmo"
    payload = record.payload
    assert payload is not None
    assert "entity_name" not in payload
    assert "user_id" not in payload
    assert "org_id" not in payload
    assert "entity_id" not in payload


# ── One serialized shape, closed by a round-trip ───────────────────────────────────────────────
#
# A base field added to `BusinessEvent` without threading it through fails here.


@dataclass(frozen=True, kw_only=True)
class _NoteEvent(BusinessEvent):
    app_name = "test_note"
    verb = "noted"
    note: str | None = None
    ref_id: uuid.UUID | None = None


def _reconstruct_through_delivery(event: BusinessEvent) -> BusinessEvent:
    """The listener's chain, without a database."""
    return type(event).from_payload(task_payload(event_to_record(event)))


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
    assert _reconstruct_through_delivery(event) == event


def test_every_lifted_field_is_a_column_of_the_record():
    assert set(LIFTED_COLUMNS) <= set(BusinessEventRecord.__mapper__.columns.keys())


# ── The write path goes through the SECURITY DEFINER writer function, not a raw INSERT ─────────


@pytest.mark.asyncio
async def test_the_write_path_calls_the_definer_function_with_the_records_columns():
    captured: dict[str, object] = {}

    class _FakeSession:
        async def execute(self, statement: object, params: object = None) -> None:
            captured["statement"] = statement
            captured["params"] = params

    record = BusinessEventRecord(
        app_name="todo", verb="created", icon="check", user_id=uuid.uuid7(), payload={"k": "v"}
    )
    await _append_record(cast(AsyncSession, _FakeSession()), record)

    assert captured["statement"] is _RECORD
    params = cast(dict, captured["params"])
    assert (params["app_name"], params["verb"], params["icon"]) == ("todo", "created", "check")
    assert params["user_id"] == record.user_id
    assert params["payload"] == json.dumps({"k": "v"})


# ── A delivered event is self-descriptive (its own instant) and correlated (the request) ───────


def _scanned_record(**over: object) -> BusinessEventRecord:
    columns: dict[str, object] = {
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
    columns.update(over)
    return BusinessEventRecord(**columns)


def test_task_payload_folds_the_fact_instant_and_the_originating_request():
    fid, rid = uuid.uuid7(), uuid.uuid7()
    instant = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    record = _scanned_record(id=fid, created_at=instant, request_id=rid, payload={"note": "hi"})
    payload = task_payload(record)
    assert payload["created_at"] == instant.isoformat()
    assert payload["request_id"] == str(rid)
    assert payload["event_id"] == str(fid)
    assert payload["note"] == "hi"


def test_a_delivered_event_carries_the_facts_instant_rebuilt_from_the_record():
    instant = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    event = _NoteEvent.from_payload({"note": "hi", "created_at": instant.isoformat()})
    assert event.created_at == instant


def test_the_emitted_event_has_no_instant_because_the_journal_is_the_clock():
    assert _NoteEvent(user_id=uuid.uuid7()).created_at is None


def test_request_id_rides_to_the_log_context_not_onto_the_event():
    event = _NoteEvent.from_payload({"request_id": str(uuid.uuid7()), "note": "x"})
    assert not hasattr(event, "request_id")


# ── The UUID-aware serializer socle: DTOs carry uuid.UUID, the edge stringifies/re-parses ──────


@dataclass(frozen=True, kw_only=True)
class _RefEvent(BusinessEvent):
    app_name = "test_ref"
    verb = "happened"
    ref_id: uuid.UUID | None = None


def test_event_to_record_stringifies_uuid_payload_fields():
    ref = uuid.uuid7()
    record = event_to_record(_RefEvent(user_id=uuid.uuid7(), ref_id=ref))
    assert record.payload is not None
    assert record.payload["ref_id"] == str(ref)


def test_event_to_record_lifts_a_uuid_entity_id():
    eid = uuid.uuid7()
    record = event_to_record(WidgetCreated(org_id=uuid.uuid7(), entity_id=eid, entity_name="Gizmo"))
    assert record.entity_id == eid


def test_from_payload_reparses_every_uuid_field_by_type():
    ref, actor = uuid.uuid7(), uuid.uuid7()
    event = _RefEvent.from_payload({"ref_id": str(ref), "user_id": str(actor)})
    assert event.ref_id == ref
    assert event.user_id == actor


def test_from_payload_is_defensive_on_unparseable_strings():
    event = _RefEvent.from_payload({"ref_id": "not-a-uuid"})
    assert event.ref_id == "not-a-uuid"


# ── A secret cannot enter a fact ───────────────────────────────────────────────────────────────


def test_a_secret_named_field_is_refused_at_class_definition():
    with pytest.raises(TypeError, match="secret material") as exc:

        @dataclass(frozen=True, kw_only=True)
        class Leaky(BusinessEvent):
            app_name = "test_secret"
            verb = "leaked"
            api_key: str | None = None

    assert "api_key_id" in str(exc.value)


@pytest.mark.parametrize(
    "field_name",
    ["access_token", "recovery_code", "otp_secret", "jwt", "credential", "user_password"],
)
def test_secret_material_is_refused_whatever_the_spelling(field_name: str):
    with pytest.raises(TypeError, match="secret material"):
        type(
            "Leaky",
            (BusinessEvent,),
            {"__annotations__": {field_name: str}, field_name: None, "app_name": "x", "verb": "y"},
        )


def test_an_id_reference_to_a_secret_bearing_entity_is_allowed():
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
    assert _is_secret_field_name("api_key_id") is False
    assert _is_secret_field_name("entity_id") is False
    assert _is_secret_field_name("title") is False


def test_from_payload_refuses_a_stored_null_for_a_required_field():
    """Dataclasses do not validate: the event would claim ``org_id=None`` against its type."""
    with pytest.raises(TypeError):
        WidgetCreated.from_payload({"org_id": None, "entity_id": str(uuid.uuid7())})


def test_from_payload_still_accepts_a_stored_null_for_an_optional_field():
    event = _RefEvent.from_payload({"user_id": None, "ref_id": None})
    assert event.user_id is None


def test_from_payload_reparses_a_uuid_entity_id():
    eid = uuid.uuid7()
    event = _RefEvent.from_payload({"entity_id": str(eid)})
    assert event.entity_id == eid


def test_two_classes_cannot_claim_the_same_kind():
    """Else the listener would rebuild stored facts into the wrong class."""

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
    """A reimported module or a test body run twice re-creates the same declaration."""

    def declare() -> type[BusinessEvent]:
        @dataclass(frozen=True, kw_only=True)
        class Same(BusinessEvent):
            app_name = "test_dup"
            verb = "redeclared"

        return Same

    declare()
    declare()
