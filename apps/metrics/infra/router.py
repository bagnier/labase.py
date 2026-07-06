from datetime import timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.metrics.domain import service
from apps.metrics.infra.repository import window_rows
from apps.shared import clock
from apps.shared.config import get_technical_settings
from apps.shared.http import wants_json
from apps.shared.http.templates import templates
from apps.shared.observability.metrics import accumulator
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession

router = APIRouter(tags=["metrics"])
exposition_router = APIRouter(tags=["metrics"])

WINDOW_HOURS = 24


@exposition_router.get("/metrics")
async def metrics_exposition(current_user: CurrentAdmin) -> PlainTextResponse:
    """Live Prometheus counters — the interop layer for real scrapers later."""
    return PlainTextResponse(
        accumulator.render_prometheus(), media_type="text/plain; version=0.0.4"
    )


@router.get("", response_model=None)
async def load_screen(
    request: Request, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    since = clock.now() - timedelta(hours=WINDOW_HOURS)
    routes, totals = service.aggregate(await window_rows(session, since))
    if wants_json(request):
        return JSONResponse(
            {
                "totals": totals.model_dump(mode="json"),
                "routes": [r.model_dump(mode="json") for r in routes],
            }
        )
    return templates.TemplateResponse(
        request,
        "metrics/load.html",
        {
            "user": current_user,
            "routes": routes,
            "totals": totals,
            "window_hours": WINDOW_HOURS,
            "studio_url": _studio_url(),
            **await fullpage_context(session, current_user),
        },
    )


def _studio_url() -> str:
    """Local stack → Studio; hosted Supabase → the project dashboard (same origin idea)."""
    api_url = get_technical_settings().supabase_api_url
    if "supabase.co" in api_url:
        return "https://supabase.com/dashboard"
    return api_url.replace(":54321", ":54323")
