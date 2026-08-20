import json
from datetime import datetime

from apps.shared import clock
from apps.shared.events.models import BusinessEventRecord
from apps.shared.observability.logging import apply_log_level
from apps.shared.observability.repository import LogRepository
from apps.timeline.tests.e2e import seed_data
from apps.timeline.tests.e2e.seed_data import timeline_org_id, timeline_request_id, timeline_user_id
from tests.e2e.drivers import api_transaction as db
from tests.e2e.drivers.api_base import ApiBase


class TimelineApiMixin(ApiBase):
    def _timeline_as_admin(self) -> None:
        as_admin = getattr(self, "_as_admin", None)  # console mixin
        assert as_admin is not None
        as_admin()

    # ── seeding (through the real write paths) ────────────────────────────────
    def _add_event(self, model: BusinessEventRecord) -> None:
        async def _do(s):
            s.add(model)

        self.run(db.seed_fixtures(_do))

    def seed_event_from_org(self, event: str, org: str, when: datetime | None = None) -> None:
        self._add_event(seed_data.event_model(event, org=timeline_org_id(org), when=when))

    def seed_many_events(self, count: int, org: str) -> None:
        """A run of facts long enough to overflow one page — added in a single transaction, since
        a hundred round trips would be the slowest arrangement in the suite."""
        models = seed_data.event_run(count, timeline_org_id(org), now=clock.now())

        async def _do(s):
            s.add_all(models)

        self.run(db.seed_fixtures(_do))

    def seed_event_by_user(self, event: str, email: str) -> None:
        self._add_event(seed_data.event_model(event, user=timeline_user_id(email)))

    def seed_event_about(self, event: str, org: str, subject: str) -> None:
        """A fact whose subject has a readable name — a todo's title, an org's. What the journal
        pins at write time and the timeline has to be searchable by."""
        self._add_event(seed_data.event_model(event, org=timeline_org_id(org), entity_name=subject))

    def _append_request(
        self,
        event: str,
        *,
        org: str | None = None,
        level: str = "info",
        when: datetime | None = None,
        request_id: str | None = None,
    ) -> None:
        # Straight into the store, bypassing the live level gate the runtime path is subject to
        # (a seeded 'info' line must survive a WARNING process level).
        line = seed_data.log_line(event, org=org, level=level, when=when, request_id=request_id)

        async def _do(s):
            await LogRepository(s).append([line], instance="test")

        self.run(db.seed_fixtures(_do))

    def seed_request_from_org(
        self, event: str, org: str, *, level: str = "info", when: datetime | None = None
    ) -> None:
        self._append_request(event, org=timeline_org_id(org), level=level, when=when)

    def _insert_error(
        self, title: str, *, org: str | None = None, request_id: str | None = None, when=None
    ) -> None:
        context = seed_data.error_context(org=org, request_id=request_id)
        params = seed_data.issue_params(title, when)

        async def _do(s):
            issue_id = (await s.execute(seed_data.INSERT_ISSUE, params)).scalar_one()
            await s.execute(
                seed_data.INSERT_OCCURRENCE,
                {"iid": issue_id, "ts": params["ts"], "context": json.dumps(context)},
            )

        self.run(db.seed_fixtures(_do))

    def seed_error_from_org(self, title: str, org: str, *, when: datetime | None = None) -> None:
        self._insert_error(title, org=timeline_org_id(org), when=when)

    def set_process_log_level(self, level: str) -> None:
        # In-process: the API driver shares the running app, so this is the live firehose level.
        apply_log_level(level)

    def seed_correlated_request(
        self, request_id: str, org: str, event: str, error: str, *, when: datetime | None = None
    ) -> None:
        # All three sources must key on the same value for the timeline to correlate them.
        oid, request_id = timeline_org_id(org), timeline_request_id(request_id)
        self._append_request("request.finished", org=oid, request_id=request_id, when=when)
        self._add_event(seed_data.event_model(event, org=oid, request_id=request_id, when=when))
        self._insert_error(error, org=oid, request_id=request_id, when=when)

    # ── reads ────────────────────────────────────────────────────────────────
    def _open_timeline(self, **params) -> None:
        self._timeline_as_admin()
        # Remember the active filter so a following export carries the same params (WYSIWYG).
        self._timeline_filter = {k: v for k, v in params.items() if v is not None}
        self.response = self.client().get(
            "/console/timeline",
            params=self._timeline_filter,
            headers={"accept": "application/json"},
        )
        assert self.response.status_code == 200, (
            f"GET /console/timeline: {self.response.status_code} {self.response.text}"
        )

    def open_timeline(self) -> None:
        self._open_timeline()

    # ── paging ───────────────────────────────────────────────────────────────
    def _subjects(self) -> list[str]:
        """What each entry is *about*. A run of facts shares one kind, so the name cannot tell
        one page's rows from the next one's — the subject can."""
        return [e["entity_name"] for e in self._entries() if e["entity_name"]]

    def load_older_entries(self) -> None:
        """Follow the cursor the screen just handed back — the API twin of clicking the button."""
        self._first_page = self._subjects()
        cursor = self.response.json()["next_before"]
        assert cursor, "the timeline offered no next page to load"
        self._open_timeline(**{**self._timeline_filter, "before": cursor})

    def assert_offers_older_entries(self) -> None:
        assert self.response.json()["next_before"], (
            f"expected a next page after {len(self._entries())} entries"
        )

    def assert_older_entries_do_not_repeat(self) -> None:
        added = self._subjects()
        assert added, "the second page came back empty"
        repeated = set(added) & set(self._first_page)
        assert not repeated, f"the second page repeats {sorted(repeated)}"

    def filter_timeline_by_org(self, org: str) -> None:
        self._open_timeline(org_id=timeline_org_id(org))

    def filter_timeline_by_user(self, email: str) -> None:
        self._open_timeline(user_id=timeline_user_id(email))

    def filter_timeline_by_source(self, source: str) -> None:
        self._open_timeline(source=source)

    def filter_timeline_by_app(self, app: str) -> None:
        self._open_timeline(app=app)

    def filter_timeline_by_level(self, level: str) -> None:
        self._open_timeline(level=level)

    def filter_timeline_by_request(self, request_id: str) -> None:
        self._open_timeline(request_id=timeline_request_id(request_id))

    def search_timeline(self, text: str) -> None:
        self._open_timeline(q=text)

    def filter_timeline_by_dates(self, a: str, b: str) -> None:
        self._open_timeline(from_dt=a, to_dt=b)

    def sort_timeline(self, column: str, direction: str) -> None:
        self._open_timeline(sort=column, dir=direction)

    def view_activity_by(self, grain: str) -> None:
        self._open_timeline(bucket=grain)

    # ── export ───────────────────────────────────────────────────────────────
    def _export_timeline(self, fmt: str) -> None:
        self._timeline_as_admin()
        params = {**getattr(self, "_timeline_filter", {}), "format": fmt}
        self.export_response = self.client().get("/console/timeline/export", params=params)
        assert self.export_response.status_code == 200, (
            f"GET export: {self.export_response.status_code} {self.export_response.text}"
        )

    def export_timeline_ndjson(self) -> None:
        self._export_timeline("ndjson")

    def export_timeline_csv(self) -> None:
        self._export_timeline("csv")

    # ── assertions ───────────────────────────────────────────────────────────
    def _entries(self) -> list[dict]:
        return self.response.json()["entries"]

    def _events(self) -> list[str]:
        return [e["name"] for e in self._entries()]

    def assert_timeline_empty(self) -> None:
        assert self._entries() == [], f"expected no entries: {self._entries()}"

    def assert_entry_listed(self, event: str) -> None:
        assert event in self._events(), f"{event!r} not listed in {self._events()}"

    def assert_entry_not_listed(self, event: str) -> None:
        assert event not in self._events(), f"{event!r} unexpectedly listed in {self._events()}"

    def assert_entry_source(self, event: str, source: str) -> None:
        found = next((e for e in self._entries() if e["name"] == event), None)
        assert found is not None, f"{event!r} not listed: {self._events()}"
        assert found["source"] == source, (
            f"{event!r} source: expected {source!r}, got {found['source']!r}"
        )

    def assert_source_count(self, source: str, expected: int, org: str) -> None:
        """How many of *this org's* rows one source contributed.

        Scoped, and not optionally: the store is shared with the running app, which writes its own
        ``request.finished`` for every page the driver loads. An exhaustive count therefore raced
        the log drain — the same assertion saw 1, 2 or 4 depending on when the batch landed.
        """
        oid = timeline_org_id(org)
        n = sum(1 for e in self._entries() if e["source"] == source and e["org_id"] == oid)
        assert n == expected, f"expected {expected} {source!r} entries, got {n}: {self._entries()}"

    def assert_all_listed(self, *events: str) -> None:
        listed = self._events()
        missing = [e for e in events if e not in listed]
        assert not missing, f"{missing!r} not all listed in {listed}"

    def assert_entry_above(self, a: str, b: str) -> None:
        events = self._events()
        assert a in events, f"{a!r} not listed: {events}"
        assert b in events, f"{b!r} not listed: {events}"
        assert events.index(a) < events.index(b), f"{a!r} not above {b!r}: {events}"

    def assert_activity(self, date: str, business: int, logs: int, issue: int) -> None:
        act = self.response.json()["activity"].get(date, {})
        assert act.get("business", 0) == business, f"activity {date} business: {act}"
        assert act.get("logs", 0) == logs, f"activity {date} logs: {act}"
        assert act.get("issue", 0) == issue, f"activity {date} issue: {act}"

    def assert_export_contains(self, needle: str) -> None:
        body = self.export_response.text
        assert needle in body, f"{needle!r} not in export:\n{body}"

    def assert_export_excludes(self, needle: str) -> None:
        assert needle not in self.export_response.text, f"{needle!r} unexpectedly in export"

    def assert_csv_export(self, needle: str) -> None:
        lines = self.export_response.text.splitlines()
        assert lines, "empty CSV export"
        assert lines[0].split(",")[0] == "ts", f"expected header row, got {lines[0]!r}"
        assert any(needle in line for line in lines[1:]), f"{needle!r} not listed in CSV rows"

    def try_open_timeline(self) -> None:
        self.response = self.client().get(
            "/console/timeline", headers={"accept": "application/json"}
        )
