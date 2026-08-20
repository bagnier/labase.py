"""What replaced the per-statement firehose: the request that surprised, and nothing else.

``db.query`` used to write one ``debug`` line per statement. It answered "what did it do", which
``request.finished`` (``db_queries``, ``db_ms``) and the journal already answer between them — and
it paid for the one thing it uniquely bought, *which* statement was slow, with a line per query on
every request of a healthy server.

So the drill-down is kept and the firehose is not: a request whose SQL crosses either threshold
writes one ``info`` line naming its slowest statements, and every request under them writes
nothing. That is the doctrine's ``info`` exactly — a point of surprise — and it correlates with
the exchange it belongs to through the ``request_id`` both lines already carry, which is why this
line repeats none of the path, method or status ``request.finished`` states.

Pure middleware logic — no DB, no running app: the statements are handed to the same accumulator
the SQLAlchemy listener feeds.
"""

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from apps.shared.observability import request, sql

_UNREACHABLE = 10_000


@pytest.fixture(autouse=True)
def _restore_thresholds():
    yield
    sql.apply_heavy_request_thresholds(queries=sql.DEFAULT_HEAVY_QUERIES, ms=sql.DEFAULT_HEAVY_MS)


def _serve(log_chain, statements: list[tuple[str, float]]):
    """Serve one request whose handler runs ``statements``; return the lines it left behind."""
    app = FastAPI()

    @app.get("/acme/todos")
    def handler() -> Response:
        stats = sql.read_request_stats()
        assert stats is not None, "the middleware must have opened a tally"
        for statement, ms in statements:
            stats.remember(statement, ms)
        return Response(status_code=200)

    app.add_middleware(request.RequestLogger)
    TestClient(app, base_url="https://example.com").get("/acme/todos")
    return log_chain()


def _named(lines) -> list[tuple[str, str]]:
    return [(line.name, line.level) for line in lines]


def test_a_request_under_both_thresholds_says_nothing_about_its_sql(log_chain):
    """The healthy case, which is nearly every request: the exchange line already carries the
    count and the time, and there is no surprise to elaborate on."""
    sql.apply_heavy_request_thresholds(queries=5, ms=_UNREACHABLE)

    lines = _serve(log_chain, [("SELECT 1", 1.0), ("SELECT 2", 1.0)])

    assert _named(lines) == [("request.finished", "info")]


def test_a_request_that_multiplies_its_queries_is_a_surprise(log_chain):
    """The N+1 — the failure mode the per-query firehose existed to catch, now catching itself."""
    sql.apply_heavy_request_thresholds(queries=3, ms=_UNREACHABLE)

    lines = _serve(log_chain, [(f"SELECT {i}", 1.0) for i in range(3)])

    assert _named(lines) == [("request.finished", "info"), ("db.heavy_request", "info")]


def test_a_request_that_spends_too_long_in_the_database_is_one_too(log_chain):
    """One slow statement is as much a surprise as forty quick ones, and neither implies the
    other — hence two thresholds, either of which is enough."""
    sql.apply_heavy_request_thresholds(queries=_UNREACHABLE, ms=200.0)

    lines = _serve(log_chain, [("SELECT pg_sleep(1)", 250.0)])

    assert _named(lines) == [("request.finished", "info"), ("db.heavy_request", "info")]


def test_the_line_names_the_slowest_statements_and_keeps_only_those(log_chain):
    """A request that ran ten thousand statements must not put ten thousand of them in a payload;
    what a reader opens the line for is the handful that cost the time — newest to slowest, and
    exactly ``_KEPT_STATEMENTS`` of them however many ran."""
    sql.apply_heavy_request_thresholds(queries=3, ms=_UNREACHABLE)
    cheap = [(f"SELECT {i}", float(i)) for i in range(1, 21)]
    dear = [("SELECT  *\n  FROM todos", 90.0), ("SELECT * FROM orgs", 80.0)]

    lines = _serve(log_chain, cheap + dear)
    heavy = next(line for line in lines if line.name == "db.heavy_request")

    assert heavy.payload["slowest"] == [
        # Squashed on the way out, never on the way in: the whitespace collapse is paid for by
        # the five statements a reader sees, not by the twenty-two the request ran.
        {"ms": 90.0, "statement": "SELECT * FROM todos"},
        {"ms": 80.0, "statement": "SELECT * FROM orgs"},
        {"ms": 20.0, "statement": "SELECT 20"},
        {"ms": 19.0, "statement": "SELECT 19"},
        {"ms": 18.0, "statement": "SELECT 18"},
    ]
