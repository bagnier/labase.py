import json
from datetime import datetime

from apps.shared.events.models import BusinessEventRecord
from apps.shared.observability.firehose import append_firehose
from apps.shared.observability.logging import apply_log_level
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

    def seed_event_by_user(self, event: str, email: str) -> None:
        self._add_event(seed_data.event_model(event, user=timeline_user_id(email)))

    def _append_request(
        self,
        event: str,
        *,
        org: str | None = None,
        level: str = "info",
        when: datetime | None = None,
        request_id: str | None = None,
    ) -> None:
        # The firehose's own writer, bypassing the live level gate the runtime path is subject
        # to (a seeded 'info' line must survive a WARNING process level).
        append_firehose(
            seed_data.firehose_record(event, org=org, level=level, when=when, request_id=request_id)
        )

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

    def seed_correlated_request(self, request_id: str, org: str, event: str, error: str) -> None:
        # All three sources must key on the same value to correlate; the journal's column is a uuid,
        # so the scenario's readable token maps to one here.
        oid, request_id = timeline_org_id(org), timeline_request_id(request_id)
        self._append_request("request.finished", org=oid, request_id=request_id)
        self._add_event(seed_data.event_model(event, org=oid, request_id=request_id))
        self._insert_error(error, org=oid, request_id=request_id)

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

    def assert_source_count(self, source: str, expected: int) -> None:
        n = sum(1 for e in self._entries() if e["source"] == source)
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

    def assert_activity(self, date: str, business: int, http: int, error: int) -> None:
        act = self.response.json()["activity"].get(date, {})
        assert act.get("business", 0) == business, f"activity {date} business: {act}"
        assert act.get("http", 0) == http, f"activity {date} http: {act}"
        assert act.get("error", 0) == error, f"activity {date} error: {act}"

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
