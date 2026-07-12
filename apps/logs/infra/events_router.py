"""The console "Business events" screen — every app's typed events, grouped per app.

The admin-wide (BYPASSRLS) counterpart to the RLS-scoped profile and dashboard timelines: it
reads the same ``business_events`` store through :func:`search_business_events` and renders one
vertical daisyUI timeline per app (the event kind's ``<app>.<verb>`` prefix), optionally focused
on a single app. Labels and moments only — the raw kind and payload never reach the page, exactly
like the member-facing timelines.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from apps.auth.contract.current import CurrentAdmin
from apps.shared.http.templates import templates
from apps.shared.observability.business_events import (
    BusinessEventRow,
    activity_entries,
    search_business_events,
)
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession

events_router = APIRouter(tags=["events"])

# The screen browses the recent window across every app; an admin narrows to one app with the
# focus chips (the logs viewer carries the same axis as a live, exportable filter).
_RECENT = 200


def _event_app(row: BusinessEventRow) -> str:
    """The owning app of a business event — the first dotted segment of its kind."""
    return row.kind.split(".", 1)[0]


def _grouped(rows: list[BusinessEventRow], focus: str | None) -> dict[str, list[dict]]:
    """Humanized entries per app, apps in alphabetical order. ``focus`` keeps a single app."""
    by_app: dict[str, list[BusinessEventRow]] = {}
    for row in rows:
        by_app.setdefault(_event_app(row), []).append(row)
    if focus:
        by_app = {focus: by_app.get(focus, [])}
    return {app: activity_entries(rows) for app, rows in sorted(by_app.items())}


@events_router.get("", response_class=HTMLResponse)
async def events_screen(
    request: Request,
    current_user: CurrentAdmin,
    session: AdminSession,
    app: str | None = None,
) -> HTMLResponse:
    rows = await search_business_events(session, limit=_RECENT)
    all_apps = sorted({_event_app(r) for r in rows})
    return templates.TemplateResponse(
        request,
        "logs/events.html",
        {
            "user": current_user,
            "apps": _grouped(rows, app or None),
            "all_apps": all_apps,
            "focus": app or "",
            **await fullpage_context(session, current_user),
        },
    )
