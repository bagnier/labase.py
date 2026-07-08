import uuid
from datetime import datetime

from sqlalchemy import text

from apps.shared import clock
from tests.e2e.drivers import api_transaction as db
from tests.e2e.drivers.api_base import ApiBase

# Deterministic ids so a seed step and a filter step agree on "Acme" / "alice@…" without
# needing a real org/user row (the timeline filters by the raw id it stored).
_NS = uuid.UUID("00000000-0000-0000-0000-00000000da7a")


def logs_org_id(name: str) -> str:
    return str(uuid.uuid5(_NS, f"org:{name}"))


def logs_user_id(email: str) -> str:
    return str(uuid.uuid5(_NS, f"user:{email}"))


_INSERT_AUDIT = text(
    "INSERT INTO audit_logs (created_at, level, event, user_id, org_id, request_id, payload) "
    "VALUES (:ts, :level, :event, CAST(:user AS uuid), CAST(:org AS uuid), :rid, NULL)"
)


class LogsApiMixin(ApiBase):
    def _logs_as_admin(self) -> None:
        as_admin = getattr(self, "_as_admin", None)  # console mixin
        assert as_admin is not None
        as_admin()

    # ── seeding ──────────────────────────────────────────────────────────────
    def _insert_audit(
        self,
        event: str,
        *,
        org: str | None = None,
        user: str | None = None,
        level: str = "info",
        when: datetime | None = None,
        request_id: str | None = None,
    ) -> None:
        async def _do(s):
            await s.execute(
                _INSERT_AUDIT,
                {
                    "ts": when or clock.now(),
                    "level": level,
                    "event": event,
                    "user": user,
                    "org": org,
                    "rid": request_id,
                },
            )

        self.run(db.seed_fixtures(_do))

    def seed_audit_from_org(self, event: str, org: str, when: datetime | None = None) -> None:
        self._insert_audit(event, org=logs_org_id(org), when=when)

    def seed_audit_by_user(self, event: str, email: str) -> None:
        self._insert_audit(event, user=logs_user_id(email))

    # ── reads ────────────────────────────────────────────────────────────────
    def _open_logs(self, **params) -> None:
        self._logs_as_admin()
        clean = {k: v for k, v in params.items() if v is not None}
        self.response = self.client().get(
            "/console/logs", params=clean, headers={"accept": "application/json"}
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

    def filter_logs_by_dates(self, a: str, b: str) -> None:
        self._open_logs(from_dt=a, to_dt=b)

    def sort_logs(self, column: str, direction: str) -> None:
        self._open_logs(sort=column, dir=direction)

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

    def assert_entry_above(self, a: str, b: str) -> None:
        events = self._events()
        assert a in events and b in events, f"{a!r}/{b!r} not both listed: {events}"
        assert events.index(a) < events.index(b), f"{a!r} not above {b!r}: {events}"

    def assert_activity(self, date: str, audit: int, request: int, issue: int) -> None:
        act = self.response.json()["activity"].get(date, {})
        assert act.get("audit", 0) == audit, f"activity {date} audit: {act}"
        assert act.get("request", 0) == request, f"activity {date} request: {act}"
        assert act.get("issue", 0) == issue, f"activity {date} issue: {act}"

    def try_open_logs_screen(self) -> None:
        self.response = self.client().get("/console/logs", headers={"accept": "application/json"})

    def assert_logs_not_found(self) -> None:
        assert self.response is not None
        assert self.response.status_code == 404, f"Expected 404, got {self.response.status_code}"
