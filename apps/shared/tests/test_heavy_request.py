"""``db.heavy_request``: one line naming the slowest statements when a request crosses a
threshold, nothing otherwise. No database: statements go straight to the accumulator."""

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from apps.shared.logs import request
from apps.shared.persistence import sql_stats

_UNREACHABLE = 10_000


@pytest.fixture(autouse=True)
def _restore_thresholds():
    yield
    sql_stats.apply_heavy_request_thresholds(
        queries=sql_stats.DEFAULT_HEAVY_QUERIES, ms=sql_stats.DEFAULT_HEAVY_MS
    )


def _serve(log_chain, statements: list[tuple[str, float]]):
    app = FastAPI()

    @app.get("/acme/todos")
    def handler() -> Response:
        stats = sql_stats.read_request_stats()
        assert stats is not None, "the middleware must have opened a tally"
        for statement, ms in statements:
            stats.remember(statement, ms)
        return Response(status_code=200)

    app.add_middleware(request.RequestLogger)
    TestClient(app, base_url="https://example.com").get("/acme/todos")
    return log_chain()


def _named(lines) -> list[tuple[str, str]]:
    return [(line.name, line.level) for line in lines]


def test_a_health_probe_never_opens_a_sql_tally(log_chain):
    """A probe's `SELECT 1` on a slow database would trip `db.heavy_request` with nothing to
    correlate it to."""
    app = FastAPI()

    @app.get("/health/ready")
    def handler() -> Response:
        assert sql_stats.read_request_stats() is None
        return Response(status_code=200)

    app.add_middleware(request.RequestLogger)
    TestClient(app, base_url="https://example.com").get("/health/ready")

    assert log_chain() == []


def test_a_request_under_both_thresholds_says_nothing_about_its_sql(log_chain):
    sql_stats.apply_heavy_request_thresholds(queries=5, ms=_UNREACHABLE)

    lines = _serve(log_chain, [("SELECT 1", 1.0), ("SELECT 2", 1.0)])

    assert _named(lines) == [("request.finished", "info")]


def test_a_request_that_multiplies_its_queries_is_a_surprise(log_chain):
    """The N+1."""
    sql_stats.apply_heavy_request_thresholds(queries=3, ms=_UNREACHABLE)

    lines = _serve(log_chain, [(f"SELECT {i}", 1.0) for i in range(3)])

    assert _named(lines) == [("request.finished", "info"), ("db.heavy_request", "info")]


def test_a_request_that_spends_too_long_in_the_database_is_one_too(log_chain):
    sql_stats.apply_heavy_request_thresholds(queries=_UNREACHABLE, ms=200.0)

    lines = _serve(log_chain, [("SELECT pg_sleep(1)", 250.0)])

    assert _named(lines) == [("request.finished", "info"), ("db.heavy_request", "info")]


def test_the_line_names_the_slowest_statements_and_keeps_only_those(log_chain):
    """Exactly ``_KEPT_STATEMENTS``, slowest first, however many ran."""
    sql_stats.apply_heavy_request_thresholds(queries=3, ms=_UNREACHABLE)
    cheap = [(f"SELECT {i}", float(i)) for i in range(1, 21)]
    dear = [("SELECT  *\n  FROM todos", 90.0), ("SELECT * FROM orgs", 80.0)]

    lines = _serve(log_chain, cheap + dear)
    heavy = next(line for line in lines if line.name == "db.heavy_request")

    assert heavy.payload["slowest"] == [
        # Whitespace is collapsed only for the statements kept.
        {"ms": 90.0, "statement": "SELECT * FROM todos"},
        {"ms": 80.0, "statement": "SELECT * FROM orgs"},
        {"ms": 20.0, "statement": "SELECT 20"},
        {"ms": 19.0, "statement": "SELECT 19"},
        {"ms": 18.0, "statement": "SELECT 18"},
    ]
