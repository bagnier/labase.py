"""BusinessEvent vocabulary + the bus/persist wiring that records it.

Covers the two mechanisms Phase 1 introduced: CRUD ``kind`` derivation (so apps write no dotted
strings) and MRO dispatch (so one subscriber on the base records every subclass), plus the
non-blocking persist contract (``emit`` never waits on — or fails from — the DB write).
"""

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from apps.shared.bus import EventBus
from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated
from apps.shared.observability.business_events import persist_business_event


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


@pytest.mark.asyncio
async def test_base_subscriber_receives_every_subclass_once():
    bus = EventBus()
    seen: list[BusinessEvent] = []

    async def record(event: BusinessEvent) -> None:
        seen.append(event)

    # Registered on the base and on the concrete type — MRO dispatch must still run it once.
    bus.on(BusinessEvent, record)
    bus.on(WidgetCreated, record)

    event = WidgetCreated(actor_id="u", org_id="o", entity_id="w", label="Gizmo")
    await bus.emit(event)

    assert seen == [event]


@pytest.mark.asyncio
async def test_persist_is_fire_and_forget_and_scoped():
    # persist schedules the write and returns before it runs; emit never awaits the DB.
    with patch(
        "apps.shared.observability.business_events.insert_business_event", new=AsyncMock()
    ) as insert:
        await persist_business_event(
            WidgetCreated(actor_id="u", org_id="o", entity_id="w", label="Gizmo")
        )
        insert.assert_not_awaited()  # coroutine built but not yet run
        await asyncio.sleep(0)  # let the created task run

    insert.assert_awaited_once()
    assert insert.await_args is not None
    kwargs = insert.await_args.kwargs
    assert kwargs["kind"] == "widget.created"
    assert kwargs["icon"] == "cube"
    assert kwargs["user_id"] == "u"
    assert kwargs["org_id"] == "o"
    # scoping fields are lifted to columns, never duplicated into the payload
    assert "actor_id" not in kwargs["payload"]
    assert "org_id" not in kwargs["payload"]
    assert kwargs["payload"]["entity_id"] == "w"
