"""BusinessEvent vocabulary + the bus/persist wiring that records it.

Covers the two mechanisms Phase 1 introduced: CRUD ``kind`` derivation (so apps write no dotted
strings) and MRO dispatch (so one subscriber on the base records every subclass), plus the
non-blocking persist contract (``emit`` never waits on — or fails from — the DB write).
"""

from dataclasses import dataclass

import pytest

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated
from apps.shared.events.bus import EventBus
from apps.shared.events.registry import EventRegistry, registry
from apps.shared.events.store import event_columns


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


def test_event_columns_lift_scoping_and_carry_metadata():
    # emit maps a BusinessEvent onto the business_events row: scoping to columns, rest to payload.
    cols = event_columns(WidgetCreated(actor_id="u", org_id="o", entity_id="w", label="Gizmo"))
    assert cols["kind"] == "widget.created"
    assert cols["icon"] == "cube"
    assert cols["user_id"] == "u"
    assert cols["org_id"] == "o"
    assert cols["entity_id"] == "w"  # the concerned entity, lifted to its own column
    # scoping fields are lifted to columns, never duplicated into the payload
    assert cols["payload"]["label"] == "Gizmo"
    assert "actor_id" not in cols["payload"]
    assert "org_id" not in cols["payload"]
    assert "entity_id" not in cols["payload"]
