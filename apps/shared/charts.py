"""Series shaping for the declarative charts.js contract (see the `chart` macro).

Routers hand these dicts to templates; the `chart` macro serialises them next to a
``[data-chart]`` target and static/js/charts.js does the rendering, themed by daisyUI.
Keeping the shaping here (not in each router) gives every graph the same grammar:
``chart_config`` assembles, ``day_buckets_series`` turns per-day dict counts into a
stacked column chart, ``sparkline`` shrinks a single series to an inline trend.
"""

from datetime import date, timedelta
from typing import Any


def chart_config(type: str, series: list[dict[str, Any]], **options: Any) -> dict[str, Any]:
    """The {"type", "series", "options"} envelope charts.js consumes."""
    return {"type": type, "series": series, "options": options}


def last_days(days: int, *, end: date) -> list[date]:
    """The `days` calendar days ending at `end`, oldest first."""
    return [end - timedelta(days=d) for d in range(days - 1, -1, -1)]


def day_buckets_series(
    buckets: dict[str, dict[str, int]],
    *,
    days: int,
    end: date,
    names: dict[str, str] | None = None,
    height: int = 240,
) -> dict[str, Any]:
    """A stacked per-day column chart from ``{iso_day: {key: count}}`` buckets
    (the shape :meth:`TimelineReader.activity` returns) over a fixed trailing window —
    missing days render as gaps of zero, so a quiet week still shows its width."""
    window = last_days(days, end=end)
    keys = sorted({k for day in buckets.values() for k in day})
    series = [
        {
            "name": (names or {}).get(key, key),
            "data": [buckets.get(d.isoformat(), {}).get(key, 0) for d in window],
        }
        for key in keys
    ]
    return chart_config(
        "bar",
        series,
        chart={"height": height, "stacked": True},
        xaxis={"categories": [d.strftime("%d %b") for d in window]},
        yaxis={"min": 0, "forceNiceScale": True},
        legend={"position": "bottom"},
    )


def sparkline(data: list[int], *, color: str = "primary", height: int = 48) -> dict[str, Any]:
    """An inline, axis-less trend line for a single series (issue occurrences, growth)."""
    return chart_config(
        "area",
        [{"name": "", "data": data}],
        colors=[color],
        chart={"height": height, "sparkline": {"enabled": True}},
        stroke={"width": 2, "curve": "smooth"},
        fill={"type": "gradient", "gradient": {"opacityFrom": 0.3, "opacityTo": 0.05}},
        tooltip={"enabled": False},
    )
