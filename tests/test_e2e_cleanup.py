"""``truncate_app_tables`` reaches every table of the live schema."""

from tests.e2e import cleanup
from tests.e2e.sql_setup import run_sql


def test_truncate_app_tables_empties_tables_nothing_references():
    run_sql(
        "INSERT INTO log_lines (ts, level, logger, name, instance) "
        "VALUES (now(), 'info', 'test', 'test.line', 'test')"
    )
    run_sql("INSERT INTO consumed_events (consumer, event_id) VALUES ('test', public.uuidv7())")
    run_sql("INSERT INTO rate_limit_counters (key, window_start) VALUES ('test', now())")

    cleanup.truncate_app_tables()

    counts = run_sql(
        "SELECT (SELECT count(*) FROM log_lines) AS log_lines,"
        "       (SELECT count(*) FROM consumed_events) AS consumed_events,"
        "       (SELECT count(*) FROM rate_limit_counters) AS rate_limit_counters",
        fetch=True,
    )[0]

    assert (counts["log_lines"], counts["consumed_events"], counts["rate_limit_counters"]) == (
        0,
        0,
        0,
    )


def test_truncate_app_tables_keeps_a_recurring_task():
    # Recurring rows are spared by cleanup: this test removes its own, before and after.
    run_sql("DELETE FROM task_queue WHERE topic = 'test.recurring'")
    run_sql("INSERT INTO task_queue (topic, recurring_seconds) VALUES ('test.recurring', 3600)")

    try:
        cleanup.truncate_app_tables()

        remaining = run_sql(
            "SELECT topic FROM task_queue WHERE topic = 'test.recurring'", fetch=True
        )

        assert [row["topic"] for row in remaining] == ["test.recurring"]
    finally:
        run_sql("DELETE FROM task_queue WHERE topic = 'test.recurring'")
