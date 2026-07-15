import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.metrics.domain import service
from apps.metrics.domain.models import LoadPoint
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
    full_since = clock.now() - timedelta(hours=WINDOW_HOURS)
    since, until, windowed = _detail_window(request, full_since)
    routes, totals = service.aggregate(await window_rows(session, since, until))

    # A drill on the chart reloads only the totals + routes for the brushed range; the
    # chart itself (the full window) stays put as the navigation surface.
    if request.headers.get("hx-request"):
        return templates.TemplateResponse(
            request,
            "metrics/_detail.html",
            {
                "routes": routes,
                "totals": totals,
                "windowed": windowed,
                "window_hours": WINDOW_HOURS,
            },
        )

    full_rows = await window_rows(session, full_since)
    series = service.timeseries(full_rows)
    if wants_json(request):
        return JSONResponse(
            {
                "totals": totals.model_dump(mode="json"),
                "routes": [r.model_dump(mode="json") for r in routes],
                "series": [p.model_dump(mode="json") for p in series],
            }
        )
    return templates.TemplateResponse(
        request,
        "metrics/load.html",
        {
            "user": current_user,
            "routes": routes,
            "totals": totals,
            "windowed": windowed,
            "has_traffic": bool(full_rows),
            "series_json": _series_chart_json(series),
            "window_hours": WINDOW_HOURS,
            "studio_url": _studio_url(),
            **await fullpage_context(session, current_user),
        },
    )


def _detail_window(
    request: Request, full_since: datetime
) -> tuple[datetime, datetime | None, bool]:
    """Resolve the totals/routes window from the chart's ``from``/``to`` brush (epoch ms).
    Absent or malformed params fall back to the full ``WINDOW_HOURS`` — a drill never errors."""
    since = _from_ms(request.query_params.get("from")) or full_since
    until = _from_ms(request.query_params.get("to"))
    windowed = since is not full_since or until is not None
    return since, until, windowed


def _from_ms(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromtimestamp(int(float(raw)) / 1000, tz=UTC)
    except TypeError, ValueError:
        return None


def _series_chart_json(series: list[LoadPoint]) -> str:
    """Shape the time series into the charts.js declarative config (an area chart)."""
    requests = [[int(p.bucket.timestamp() * 1000), p.requests] for p in series]
    errors = [[int(p.bucket.timestamp() * 1000), p.errors] for p in series]
    return json.dumps(
        {
            "type": "area",
            "series": [
                {"name": "Requests", "data": requests},
                {"name": "Errors", "data": errors},
            ],
            # Brushing the chart reloads #load-detail for the selected range (charts.js).
            "drilldown": {"url": "/console/load", "target": "#load-detail"},
            "options": {
                "colors": ["primary", "error"],
                "chart": {"height": 240, "stacked": False},
                # Stepline, not a spline: each step is exactly one bucket's count — no
                # interpolated dips or phantom peaks between the real data points.
                "stroke": {"curve": "stepline"},
                "xaxis": {"type": "datetime"},
                "yaxis": {"min": 0, "forceNiceScale": True},
                "fill": {"type": "gradient", "gradient": {"opacityFrom": 0.35, "opacityTo": 0.05}},
            },
        }
    )


def _studio_url() -> str:
    """Local stack → Studio; hosted Supabase → the project dashboard (same origin idea)."""
    api_url = get_technical_settings().supabase_api_url
    if "supabase.co" in api_url:
        return "https://supabase.com/dashboard"
    return api_url.replace(":54321", ":54323")
