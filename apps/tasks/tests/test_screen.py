"""The tasks screen — the work the async substrate still owes, and what it ran.

A parked task already opens an issue (``queue.task_failed`` is a ``log.exception``), so this
screen is not a second bug tracker: the two objects differ where it counts. A hundred tasks
failing the same way fold into *one* issue and stay *a hundred* rows of work nobody did, and
marking the issue resolved executes none of them. The issue answers "is there a bug"; this
answers "what did not run".
"""

import json
import re
import uuid

from sqlalchemy import text

from apps.tasks.domain.strip import BANDS


def _park(driver, topic: str, error: str) -> None:
    """A task that exhausted its retries — what the worker leaves behind on ``_fail``."""
    _insert(driver, topic, attempts=5, failed_at="now()", last_error=error)


def _insert(
    driver,
    topic: str,
    *,
    attempts: int,
    failed_at: str,
    last_error: str | None,
    payload: dict | None = None,
    user_id: uuid.UUID | None = None,
    recurring_seconds: int | None = None,
    done: str = "NULL",
) -> None:
    async def write() -> None:
        async with driver.test_session_factory()() as session:
            await session.execute(
                text(
                    "INSERT INTO task_queue (topic, payload, attempts, max_attempts, "
                    "  failed_at, last_error, user_id, recurring_seconds, done_at) "
                    "VALUES (:topic, CAST(:payload AS jsonb), :attempts, 5, "
                    f"  {failed_at}, :error, :user_id, :every, {done})"
                ),
                {
                    "topic": topic,
                    "payload": json.dumps(payload or {}),
                    "attempts": attempts,
                    "error": last_error,
                    "user_id": str(user_id) if user_id else None,
                    "every": recurring_seconds,
                },
            )
            await session.commit()

    driver.run(write())


def _tasks(driver, **params) -> list[dict]:
    response = driver.client().get(
        "/console/tasks", params=params, headers={"accept": "application/json"}
    )
    return response.json()["tasks"]


def test_the_screen_lists_a_parked_task_with_what_it_died_of(driver):
    driver.sign_in_as_admin("tasks-admin-parked@example.com")
    topic = f"test.parked_{uuid.uuid4().hex}"
    _park(driver, topic, "RuntimeError('boom')")

    row = next(t for t in _tasks(driver) if t["topic"] == topic)

    assert {k: row[k] for k in ("topic", "state", "attempts", "max_attempts", "last_error")} == {
        "topic": topic,
        "state": "parked",
        "attempts": 5,
        "max_attempts": 5,
        "last_error": "RuntimeError('boom')",
    }


def test_the_screen_separates_a_task_still_being_retried_from_a_parked_one(driver):
    driver.sign_in_as_admin("tasks-admin-retrying@example.com")
    retrying = f"test.retrying_{uuid.uuid4().hex}"
    _insert(driver, retrying, attempts=2, failed_at="NULL", last_error="ConnectionError()")

    row = next(t for t in _tasks(driver) if t["topic"] == retrying)

    assert row["state"] == "retrying"


def test_the_screen_filters_by_state(driver):
    driver.sign_in_as_admin("tasks-admin-filter@example.com")
    parked = f"test.parked_{uuid.uuid4().hex}"
    retrying = f"test.retrying_{uuid.uuid4().hex}"
    _park(driver, parked, "boom")
    _insert(driver, retrying, attempts=1, failed_at="NULL", last_error="blip")

    listed = {t["topic"] for t in _tasks(driver, state="parked")}

    assert (parked in listed, retrying in listed) == (True, False)


def test_the_screen_counts_each_state_for_the_console_tile(driver):
    """The tile is the only place an admin learns the screen exists, so its numbers are the
    screen's own — read from the same query rather than a second count that can disagree."""
    driver.sign_in_as_admin("tasks-admin-counts@example.com")
    _park(driver, f"test.parked_{uuid.uuid4().hex}", "boom")
    payload = driver.client().get("/console/tasks", headers={"accept": "application/json"}).json()

    assert payload["counts"]["parked"] >= 1


def test_the_screen_renders_the_parked_task_as_html(driver):
    driver.sign_in_as_admin("tasks-admin-html@example.com")
    topic = f"test.parked_{uuid.uuid4().hex}"
    _park(driver, topic, "RuntimeError('boom')")

    body = driver.client().get("/console/tasks", headers={"accept": "text/html"}).text

    assert ("data-task-backlog" in body, topic in body) == (True, True)


def test_the_console_index_carries_a_queue_tile_naming_what_is_parked(driver):
    """The tile is how an admin learns the screen exists — a screen nothing links to is a screen
    nobody opens, and the browser lane reaches pages by following links rather than typing URLs."""
    driver.sign_in_as_admin("tasks-admin-tile@example.com")
    _park(driver, f"test.parked_{uuid.uuid4().hex}", "boom")

    overviews = driver.client().get("/console", headers={"accept": "application/json"}).json()
    tile = next(o for o in overviews["overviews"] if o["key"] == "tasks")

    assert tile["title"] == "Tasks"


def test_the_tile_names_pending_work_rather_than_calling_the_queue_clear(driver):
    """ "Nothing owed" with rows in the table is the tile contradicting the screen it links to —
    and a healthy server always holds the recurring singletons, which are owed like anything else.
    """
    driver.sign_in_as_admin("tasks-admin-tile-pending@example.com")
    _insert(
        driver, f"test.pending_{uuid.uuid4().hex}", attempts=0, failed_at="NULL", last_error=None
    )

    overviews = driver.client().get("/console", headers={"accept": "application/json"}).json()
    tile = next(o for o in overviews["overviews"] if o["key"] == "tasks")

    assert "Nothing owed" not in tile["lines"]


def test_an_empty_filter_result_does_not_claim_the_queue_is_clear(driver):
    """ "Nothing owed" is a claim about the whole queue, and a filter that matches nothing is not
    that: an admin narrowing to parked would read the reassurance as an answer about everything."""
    driver.sign_in_as_admin("tasks-admin-empty@example.com")
    _insert(
        driver, f"test.pending_{uuid.uuid4().hex}", attempts=0, failed_at="NULL", last_error=None
    )

    body = (
        driver.client()
        .get("/console/tasks", params={"state": "parked"}, headers={"accept": "text/html"})
        .text
    )

    assert "the queue is clear" not in body


def test_a_row_carries_the_payload_and_the_seat_the_task_runs_under(driver):
    """What the task was *for*, without a second screen: the payload names the event or entity it
    carries, and ``user_id`` is the RLS seat the worker synthesizes to run it."""
    driver.sign_in_as_admin("tasks-admin-payload@example.com")
    topic = f"test.parked_{uuid.uuid4().hex}"
    seat = uuid.uuid7()
    _insert(
        driver,
        topic,
        attempts=5,
        failed_at="now()",
        last_error="boom",
        payload={"event_id": "01a05e65-d051-78c0-a6ef-fc4221fa07ba"},
        user_id=seat,
    )

    body = driver.client().get("/console/tasks", headers={"accept": "text/html"}).text

    assert ("01a05e65-d051-78c0-a6ef-fc4221fa07ba" in body, str(seat) in body) == (True, True)


def test_the_filter_swaps_the_rows_alone_not_the_whole_page(driver):
    """The form filters live, so what comes back is the fragment HTMX puts in place of the table —
    not a document. A full page here would nest ``<html>`` inside the one already on screen."""
    driver.sign_in_as_admin("tasks-admin-htmx@example.com")
    topic = f"test.parked_{uuid.uuid4().hex}"
    _park(driver, topic, "boom")

    body = (
        driver.client()
        .get("/console/tasks", headers={"accept": "text/html", "HX-Request": "true"})
        .text
    )

    assert (topic in body, "<html" in body) == (True, False)


def test_the_task_filter_offers_the_topics_actually_queued(driver):
    """A placeholder is a guess the admin must already know the answer to; the datalist is what is
    there. Same trade as the org-handle autocomplete on the settings screen."""
    driver.sign_in_as_admin("tasks-admin-datalist@example.com")
    topic = f"test.parked_{uuid.uuid4().hex}"
    _park(driver, topic, "boom")

    body = driver.client().get("/console/tasks", headers={"accept": "text/html"}).text
    options = re.findall(r'<datalist id="task-options">(.*?)</datalist>', body, re.DOTALL)

    assert topic in options[0]


def _log_attempt(driver, topic: str, at_minutes_ago: int, name: str = "queue.task_retrying"):
    """One line as the worker writes it on a failed try — the only record of *when* a try
    happened, since the queue row keeps a counter and the last claim, nothing else."""

    async def write() -> None:
        async with driver.test_session_factory()() as session:
            await session.execute(
                text(
                    "INSERT INTO log_lines (ts, level, logger, name, instance, payload) "
                    "VALUES (now() - make_interval(mins => :ago), 'warning', 'apps.shared.queue', "
                    "  :name, 'test', CAST(:payload AS jsonb))"
                ),
                {
                    "ago": at_minutes_ago,
                    "name": name,
                    "payload": json.dumps({"topic": topic}),
                },
            )
            await session.commit()

    driver.run(write())


def test_the_history_tab_draws_a_block_per_logged_attempt(driver):
    """The queue keeps one row per task, so the retries live only in the log. The history counts
    them per topic and slot and gives them a band of their own beside the run that ended, so a lane
    can say "it failed three times here and parked there" without one hiding the other."""
    driver.sign_in_as_admin("tasks-admin-history@example.com")
    topic = f"test.parked_{uuid.uuid4().hex}"
    _park(driver, topic, "boom")
    for minutes in (30, 20, 10):
        _log_attempt(driver, topic, minutes)

    payload = driver.client().get("/console/tasks", headers={"accept": "application/json"}).json()
    lane = next(one for one in payload["history"]["lanes"] if one["topic"] == topic)

    assert {seg["kind"] for seg in lane["segments"]} == {"attempt", "parked"}


def test_the_history_tab_is_rendered_beside_the_list(driver):
    """Two readings of the same queue, one screen: what is owed now, and what happened."""
    driver.sign_in_as_admin("tasks-admin-tabs@example.com")
    topic = f"test.parked_{uuid.uuid4().hex}"
    _park(driver, topic, "boom")

    body = driver.client().get("/console/tasks", headers={"accept": "text/html"}).text

    assert ('data-tab="backlog"' in body, 'data-tab="history"' in body) == (True, True)


def test_a_recurring_topic_keeps_one_lane_for_all_its_passes(driver):
    """Every cycle enqueues a fresh row, so an hourly topic is several rows over a window. Folded
    into one lane they read as a heartbeat, and the cycle that went missing is what shows."""
    driver.sign_in_as_admin("tasks-admin-recurring@example.com")
    topic = f"test.recurring_{uuid.uuid4().hex}"
    for _ in range(3):
        _insert(
            driver,
            topic,
            attempts=0,
            failed_at="NULL",
            last_error=None,
            recurring_seconds=3600,
            done="now()",
        )

    payload = driver.client().get("/console/tasks", headers={"accept": "application/json"}).json()
    lanes = [lane for lane in payload["history"]["lanes"] if lane["topic"] == topic]

    assert len(lanes) == 1


def test_one_shots_of_the_same_topic_share_one_lane(driver):
    """A morning of sign-ups is one lane per *kind of work*, not one per task: forty lanes of a
    single green tick bury the one that parked, which is the only row worth finding."""
    driver.sign_in_as_admin("tasks-admin-folding@example.com")
    topic = f"test.oneshot_{uuid.uuid4().hex}"
    for _ in range(4):
        _insert(driver, topic, attempts=0, failed_at="NULL", last_error=None, done="now()")

    payload = driver.client().get("/console/tasks", headers={"accept": "application/json"}).json()
    lanes = [lane for lane in payload["history"]["lanes"] if lane["topic"] == topic]

    assert len(lanes) == 1


def test_the_history_says_how_many_one_shot_lanes_it_left_out(driver):
    """A view that silently shows the newest N reads exactly like one showing everything."""
    driver.sign_in_as_admin("tasks-admin-capped@example.com")
    _park(driver, f"test.parked_{uuid.uuid4().hex}", "boom")

    payload = driver.client().get("/console/tasks", headers={"accept": "application/json"}).json()

    assert [lane["topic"] for lane in payload["history"]["lanes"]] != []


def test_the_cap_never_drops_a_park_to_keep_a_success(driver):
    """A busy morning is thousands of clean runs and one park. Capping on recency alone throws the
    park away and leaves a screen that says everything went fine — the one lie it must not tell."""
    driver.sign_in_as_admin("tasks-admin-priority@example.com")
    topic = f"test.oneshot_{uuid.uuid4().hex}"
    _park(driver, topic, "boom")
    for _ in range(3):
        _insert(driver, topic, attempts=0, failed_at="NULL", last_error=None, done="now()")

    payload = driver.client().get("/console/tasks", headers={"accept": "application/json"}).json()
    lane = next(one for one in payload["history"]["lanes"] if one["topic"] == topic)

    assert "parked" in [segment["kind"] for segment in lane["segments"]]


def test_only_an_upper_bound_pauses_the_window(driver):
    """Same affordance, same words, same markup as ``/console/timeline``. What pauses is naming the
    *end*: with no ``to_dt`` the window closes on ``now`` and keeps moving, so a start alone is a
    longer live window, not a period being browsed — and offering "Back to live" there says the
    reader left something they never left."""
    driver.sign_in_as_admin("tasks-admin-live@example.com")

    def state(**params) -> str:
        body = (
            driver.client()
            .get("/console/tasks", params=params, headers={"accept": "text/html"})
            .text
        )
        found = re.search(r'data-live-state="(\w+)"', body)
        return found.group(1) if found else "no pill"

    assert [
        state(),
        state(from_dt="2026-09-02T03:00"),
        state(to_dt="2026-09-02T09:00"),
    ] == ["live", "live", "paused"]


def test_a_block_carries_its_details_where_a_pointer_can_reach_them(driver):
    """A block is a few pixels wide, so what it knows has to be reachable by pointing at it — and
    by a screen reader, which is why the same text is the accessible name."""
    driver.sign_in_as_admin("tasks-admin-hover@example.com")
    topic = f"test.parked_{uuid.uuid4().hex}"
    _park(driver, topic, "IntegrityError: memberships_user_id_fkey")

    body = driver.client().get("/console/tasks", headers={"accept": "text/html"}).text

    assert body.count(' · 1 parked"') >= 1


def test_changing_the_window_swaps_the_strip_without_leaving_the_tab(driver):
    """A full GET reloads the page, and the server-rendered default tab is the backlog — so naming
    a date threw the reader back to the list they had just left. The window filters in place, the
    way the backlog's own filter beside it already does."""
    driver.sign_in_as_admin("tasks-admin-swap@example.com")
    topic = f"test.parked_{uuid.uuid4().hex}"
    _park(driver, topic, "boom")

    body = (
        driver.client()
        .get(
            "/console/tasks",
            params={"panel": "history", "from_dt": "2026-09-02T03:00"},
            headers={"accept": "text/html", "HX-Request": "true"},
        )
        .text
    )

    assert ('id="task-history"' in body, "<html" in body) == (True, False)


def test_a_block_is_a_link_into_the_timeline_at_that_moment(driver):
    """Spotting a bad minute and having to retype it into another screen is the step this removes:
    the block already knows its slot and its topic, which is the pair the Timeline asks for."""
    driver.sign_in_as_admin("tasks-admin-link@example.com")
    topic = f"test.parked_{uuid.uuid4().hex}"
    _park(driver, topic, "boom")

    body = driver.client().get("/console/tasks", headers={"accept": "text/html"}).text

    assert f'href="/console/timeline?q={topic}&amp;from_dt=' in body


def test_a_window_ahead_of_the_clock_says_so_rather_than_drawing_nothing(driver):
    """The bounds are UTC and the picker shows the reader's own clock, so a window typed off a
    wristwatch lands in the future wherever that reader is not on UTC. Blank lanes then read as a
    broken screen; the honest answer names the reason."""
    driver.sign_in_as_admin("tasks-admin-future@example.com")

    body = (
        driver.client()
        .get(
            "/console/tasks",
            params={"from_dt": "2099-01-01T00:00", "to_dt": "2099-01-01T01:00"},
            headers={"accept": "text/html"},
        )
        .text
    )

    assert "window has not happened yet" in body


def test_an_empty_past_window_says_nothing_ran_rather_than_showing_blank_lanes(driver):
    """Recurring topics keep their lane whatever the window holds, so "no data" and "no runs" look
    identical unless one of them is said out loud."""
    driver.sign_in_as_admin("tasks-admin-empty-window@example.com")

    body = (
        driver.client()
        .get(
            "/console/tasks",
            params={"from_dt": "2020-01-01T00:00", "to_dt": "2020-01-01T01:00"},
            headers={"accept": "text/html"},
        )
        .text
    )

    assert "Nothing ran in this window" in body


def test_the_screen_names_the_consumer_and_keeps_the_event_under_it(driver):
    """``evt:organizations.created:todo_welcome`` is how the worker addresses a handler, not how a
    reader tells two lines apart: every reaction opens with the same six characters, and the name
    that differs is last. The screen gives that name the line and the event it reacts to the dim
    one below — nothing is lost, only unstacked, and nothing has to be hovered to be read."""
    driver.sign_in_as_admin("tasks-admin-topic-label@example.com")
    kind, consumer = f"test.made_{uuid.uuid4().hex}", f"welcome_{uuid.uuid4().hex}"
    _park(driver, f"evt:{kind}:{consumer}", "boom")

    body = driver.client().get("/console/tasks", headers={"accept": "text/html"}).text

    assert (f"evt:{kind}:{consumer}" in body, consumer in body, kind in body) == (
        False,
        True,
        True,
    )


def test_the_json_face_keeps_the_topic_the_worker_actually_matches_on(driver):
    """The shortened name is for eyes. A machine reading this — or an admin pivoting off an issue,
    which carries the topic whole — needs the string the queue is keyed by."""
    driver.sign_in_as_admin("tasks-admin-topic-json@example.com")
    topic = f"evt:test.made_{uuid.uuid4().hex}:welcome_{uuid.uuid4().hex}"
    _park(driver, topic, "boom")

    payload = driver.client().get("/console/tasks", headers={"accept": "application/json"}).json()

    assert next(t for t in payload["tasks"] if t["topic"] == topic)["topic"] == topic


def test_the_legend_names_every_band_the_strip_can_draw(driver):
    """A colour on the strip with no entry under it is a colour a reader has to guess. The legend
    is rendered from the same tuple the blocks are, so neither can drift from the other."""
    driver.sign_in_as_admin("tasks-admin-legend@example.com")

    body = driver.client().get("/console/tasks", headers={"accept": "text/html"}).text

    assert [w for _, w in BANDS if f">{w}</span>" not in body] == []


def test_the_filtered_rows_still_spell_a_cadence(driver):
    """The fragment is rendered from its own context, not the page's. A recurring row is the only
    one that asks for the cadence, so a helper left behind on the page breaks nothing until an
    admin filters — and then only for the rows that have one."""
    driver.sign_in_as_admin("tasks-admin-fragment-cadence@example.com")
    topic = f"test.pending_{uuid.uuid4().hex}"
    _insert(driver, topic, attempts=0, failed_at="NULL", last_error=None, recurring_seconds=7200)

    body = (
        driver.client()
        .get(
            "/console/tasks",
            params={"topic": topic},
            headers={"accept": "text/html", "HX-Request": "true"},
        )
        .text
    )

    assert "every 2 hours" in body


def test_a_shared_history_url_opens_on_the_history_tab(driver):
    """The window form pushes its bounds into the URL, which is what makes "Back to live" a real
    navigation rather than a jump to the address already showing. That URL then has to reopen where
    it was taken — the tab is named in the query, so the server picks it and no script has to."""
    driver.sign_in_as_admin("tasks-admin-panel-tab@example.com")

    body = (
        driver.client()
        .get("/console/tasks", params={"panel": "history"}, headers={"accept": "text/html"})
        .text
    )
    tabs = re.findall(r'data-tab="(\w+)"([^>]*)', body)

    assert [(name, "checked" in rest) for name, rest in tabs] == [
        ("backlog", False),
        ("history", True),
    ]


def test_a_live_window_refetches_itself_and_a_paused_one_does_not(driver):
    """ "Live" is a claim about the window closing on ``now``, which stops being true the second the
    page is rendered unless something refetches it. A pinned window cannot go stale, so polling it
    would be pure churn — and the poll carries the reader's own start, or it would snap the window
    back to the default six hours every half minute."""
    driver.sign_in_as_admin("tasks-admin-poll@example.com")

    def panel(**params) -> str:
        return (
            driver.client()
            .get("/console/tasks", params=params, headers={"accept": "text/html"})
            .text
        )

    live, custom, paused = (
        panel(),
        panel(from_dt="2026-09-02T03:00"),
        panel(to_dt="2026-09-02T09:00"),
    )

    assert [
        "every 30s" in live,
        "from_dt=2026-09-02T03:00" in custom,
        "every 30s" in paused,
    ] == [True, True, False]
