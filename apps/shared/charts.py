"""Chart configs for the ``chart`` template macro, which static/js/charts.js renders. Shaped here
so every graph shares one grammar.
"""

from datetime import date, timedelta
from typing import Any


def chart_config(type: str, series: list[dict[str, Any]], **options: Any) -> dict[str, Any]:
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
    """A stacked column per day from ``{iso_day: {key: count}}`` (as
    :meth:`TimelineReader.activity` returns), missing days at zero."""
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
    """An inline trend line, no axes."""
    return chart_config(
        "area",
        [{"name": "", "data": data}],
        colors=[color],
        chart={"height": height, "sparkline": {"enabled": True}},
        stroke={"width": 2, "curve": "smooth"},
        fill={"type": "gradient", "gradient": {"opacityFrom": 0.3, "opacityTo": 0.05}},
        tooltip={"enabled": False},
    )
