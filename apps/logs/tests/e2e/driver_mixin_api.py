import json
from datetime import datetime

from apps.logs.tests.e2e import seed_data
from apps.logs.tests.e2e.seed_data import logs_org_id, logs_user_id
from apps.shared.observability.business_events import BusinessEventLog
from apps.shared.observability.firehose import append_firehose
from apps.shared.observability.logging import apply_log_level
from tests.e2e.drivers import api_transaction as db
from tests.e2e.drivers.api_base import ApiBase


class LogsApiMixin(ApiBase):
    def _logs_as_admin(self) -> None:
        as_admin = getattr(self, "_as_admin", None)  # console mixin
        assert as_admin is not None
        as_admin()

    # ── seeding (through the real write paths) ────────────────────────────────
    def _add_audit(self, model: BusinessEventLog) -> None:
        async def _do(s):
            s.add(model)

        self.run(db.seed_fixtures(_do))

    def seed_audit_from_org(self, event: str, org: str, when: datetime | None = None) -> None:
        self._add_audit(seed_data.audit_model(event, org=logs_org_id(org), when=when))

    def seed_audit_by_user(self, event: str, email: str) -> None:
        self._add_audit(seed_data.audit_model(event, user=logs_user_id(email)))

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
        self._append_request(event, org=logs_org_id(org), level=level, when=when)

    def _insert_error(
        self, title: str, *, org: str | None = None, request_id: str | None = None, when=None
    ) -> None:
        context = seed_data.error_context(org=org, request_id=request_id)
        gp = seed_data.group_params(title, when)

        async def _do(s):
            gid = (await s.execute(seed_data.INSERT_ERROR_GROUP, gp)).scalar_one()
            await s.execute(
                seed_data.INSERT_ERROR_EVENT,
                {"gid": gid, "ts": gp["ts"], "context": json.dumps(context)},
            )

        self.run(db.seed_fixtures(_do))

    def seed_error_from_org(self, title: str, org: str, *, when: datetime | None = None) -> None:
        self._insert_error(title, org=logs_org_id(org), when=when)

    def set_process_log_level(self, level: str) -> None:
        # In-process: the API driver shares the running app, so this is the live firehose level.
        apply_log_level(level)

    def seed_correlated_request(self, request_id: str, org: str, audit: str, error: str) -> None:
        oid = logs_org_id(org)
        self._append_request("request.finished", org=oid, request_id=request_id)
        self._add_audit(seed_data.audit_model(audit, org=oid, request_id=request_id))
        self._insert_error(error, org=oid, request_id=request_id)

    # ── reads ────────────────────────────────────────────────────────────────
    def _open_logs(self, **params) -> None:
        self._logs_as_admin()
        # Remember the active filter so a following export carries the same params (WYSIWYG).
        self._logs_filter = {k: v for k, v in params.items() if v is not None}
        self.response = self.client().get(
            "/console/logs", params=self._logs_filter, headers={"accept": "application/json"}
        )
        assert self.response.status_code == 200, (
            f"GET /console/logs: {self.response.status_code} {self.response.text}"
        )

    def open_logs_screen(self) -> None:
        self._open_logs()

    def filter_logs_by_org(self, org: str) -> None:
        self._open_logs(org_id=logs_org_id(org))

    def filter_logs_by_user(self, email: str) -> None:
        self._open_logs(user_id=logs_user_id(email))

    def filter_logs_by_source(self, source: str) -> None:
        self._open_logs(source=source)

    def filter_logs_by_level(self, level: str) -> None:
        self._open_logs(level=level)

    def filter_logs_by_request(self, request_id: str) -> None:
        self._open_logs(request_id=request_id)

    def search_logs(self, text: str) -> None:
        self._open_logs(q=text)

    def filter_logs_by_dates(self, a: str, b: str) -> None:
        self._open_logs(from_dt=a, to_dt=b)

    def sort_logs(self, column: str, direction: str) -> None:
        self._open_logs(sort=column, dir=direction)

    # ── export ───────────────────────────────────────────────────────────────
    def _export_logs(self, fmt: str) -> None:
        self._logs_as_admin()
        params = {**getattr(self, "_logs_filter", {}), "format": fmt}
        self.export_response = self.client().get("/console/logs/export", params=params)
        assert self.export_response.status_code == 200, (
            f"GET export: {self.export_response.status_code} {self.export_response.text}"
        )

    def export_logs_ndjson(self) -> None:
        self._export_logs("ndjson")

    def export_logs_csv(self) -> None:
        self._export_logs("csv")

    # ── assertions ───────────────────────────────────────────────────────────
    def _entries(self) -> list[dict]:
        assert self.response is not None
        return self.response.json()["entries"]

    def _events(self) -> list[str]:
        return [e["event"] for e in self._entries()]

    def assert_logs_empty(self) -> None:
        assert self._entries() == [], f"expected no entries: {self._entries()}"

    def assert_entry_listed(self, event: str) -> None:
        assert event in self._events(), f"{event!r} not listed in {self._events()}"

    def assert_entry_not_listed(self, event: str) -> None:
        assert event not in self._events(), f"{event!r} unexpectedly listed in {self._events()}"

    def assert_entry_source(self, event: str, source: str) -> None:
        found = next((e for e in self._entries() if e["event"] == event), None)
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
        assert a in events and b in events, f"{a!r}/{b!r} not both listed: {events}"
        assert events.index(a) < events.index(b), f"{a!r} not above {b!r}: {events}"

    def assert_activity(self, date: str, audit: int, request: int, issue: int) -> None:
        assert self.response is not None
        act = self.response.json()["activity"].get(date, {})
        assert act.get("audit", 0) == audit, f"activity {date} audit: {act}"
        assert act.get("request", 0) == request, f"activity {date} request: {act}"
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

    def try_open_logs_screen(self) -> None:
        self.response = self.client().get("/console/logs", headers={"accept": "application/json"})
