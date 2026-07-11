"""Series shaping for the declarative charts.js contract."""

from datetime import date

from apps.shared.charts import day_buckets_series, sparkline


def test_day_buckets_series_fills_quiet_days_with_zero():
    today = date(2026, 7, 11)
    config = day_buckets_series(
        {today.isoformat(): {"audit": 3}}, days=5, end=today, names={"audit": "Audit"}
    )
    assert config["type"] == "bar"
    assert config["series"] == [{"name": "Audit", "data": [0, 0, 0, 0, 3]}]
    assert len(config["options"]["xaxis"]["categories"]) == 5
    assert config["options"]["chart"]["stacked"] is True


def test_sparkline_is_axisless_and_single_series():
    config = sparkline([1, 2, 3])
    assert config["series"] == [{"name": "", "data": [1, 2, 3]}]
    assert config["options"]["chart"]["sparkline"] == {"enabled": True}
