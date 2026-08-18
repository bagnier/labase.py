import json
from datetime import datetime

from apps.shared.events.models import BusinessEventRecord
from apps.shared.observability.firehose import append_firehose
from apps.shared.observability.logging import apply_log_level
from apps.timeline.tests.e2e import seed_data
from apps.timeline.tests.e2e.seed_data import timeline_org_id, timeline_request_id, timeline_user_id
from tests.e2e.drivers.browser_base import BrowserBase


class TimelineBrowserMixin(BrowserBase):
    def _timeline_as_admin(self) -> None:
        as_admin = getattr(self, "_as_admin", None)  # console mixin
        assert as_admin is not None
        as_admin()

    def _run_seed(self, fn) -> None:
        # ``_seed`` (learning mixin) commits fixtures on a fresh session — the browser driver has
        # no shared rolled-back transaction, so event rows must be committed and are scrubbed by
        # the per-scenario isolation fixture + browser teardown.
        seed = getattr(self, "_seed", None)
        assert seed is not None
        seed(fn)

    # ── seeding (through the real write paths) ────────────────────────────────
    def _add_event(self, model: BusinessEventRecord) -> None:
        async def _do(s):
            s.add(model)

        self._run_seed(_do)

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

        self._run_seed(_do)

    def seed_event_from_org(self, event: str, org: str, when: datetime | None = None) -> None:
        self._add_event(seed_data.event_model(event, org=timeline_org_id(org), when=when))

    def seed_event_by_user(self, event: str, email: str) -> None:
        self._add_event(seed_data.event_model(event, user=timeline_user_id(email)))

    def seed_request_from_org(
        self, event: str, org: str, *, level: str = "info", when: datetime | None = None
    ) -> None:
        append_firehose(
            seed_data.firehose_record(event, org=timeline_org_id(org), level=level, when=when)
        )

    def seed_error_from_org(self, title: str, org: str, *, when: datetime | None = None) -> None:
        self._insert_error(title, org=timeline_org_id(org), when=when)

    def set_process_log_level(self, level: str) -> None:
        # The browser app runs in-process, so this is the live firehose level.
        apply_log_level(level)

    def seed_correlated_request(self, request_id: str, org: str, event: str, error: str) -> None:
        # All three sources must key on the same value for the timeline to correlate them.
        oid, request_id = timeline_org_id(org), timeline_request_id(request_id)
        append_firehose(
            seed_data.firehose_record("request.finished", org=oid, request_id=request_id)
        )
        self._add_event(seed_data.event_model(event, org=oid, request_id=request_id))
        self._insert_error(error, org=oid, request_id=request_id)

    # ── navigation / filters (follow links, submit the real form) ─────────────
    def open_timeline(self) -> None:
        self._timeline_as_admin()
        self.last_response = self.page.goto(f"{self.base_url}/console/timeline", wait_until="load")

    def _on_timeline(self) -> None:
        if "/console/timeline" not in (self.page.url or ""):
            self.open_timeline()

    def _submit_filter(self, **fields: str) -> None:
        """Fill the on-screen filter controls and let them apply — no URL crafting.

        Values are set without firing events: the live controls auto-submit on change,
        so a Playwright ``fill()`` per field would navigate once per field and race the
        assertions. One silent set per field, then one ``requestSubmit()`` — the same
        submission path their onchange uses, exactly once."""
        self.open_timeline()
        control = None
        for name, value in fields.items():
            control = self.page.locator(f"[name='{name}']").first
            control.evaluate("(el, v) => { el.value = v }", value)
        assert control is not None, "no filter fields to submit"
        with self.page.expect_navigation(wait_until="load"):
            control.evaluate("el => el.form.requestSubmit()")

    def _pick_combobox(self, name: str, value: str) -> None:
        """Drive a smart combobox pill: open it, click the option carrying the exact value.
        Selecting by ``data-value`` (not the visible label) keeps this decoupled from label
        resolution — a seeded org id has no real handle, so its label is a truncated uuid."""
        self.open_timeline()
        self.page.locator(f"[data-filter-toggle='{name}']").click()
        option = self.page.locator(f"[data-filter-pop='{name}'] [data-value='{value}']").first
        with self.page.expect_navigation(wait_until="load"):
            option.click()

    def filter_timeline_by_org(self, org: str) -> None:
        self._pick_combobox("org_id", timeline_org_id(org))

    def filter_timeline_by_user(self, email: str) -> None:
        self._pick_combobox("user_id", timeline_user_id(email))

    def filter_timeline_by_source(self, source: str) -> None:
        self._pick_combobox("source", source)

    def filter_timeline_by_app(self, app: str) -> None:
        self._pick_combobox("app", app)

    def filter_timeline_by_level(self, level: str) -> None:
        self._pick_combobox("level", level)

    def filter_timeline_by_request(self, request_id: str) -> None:
        self._pick_combobox("request_id", timeline_request_id(request_id))

    def search_timeline(self, text: str) -> None:
        self._submit_filter(q=text)

    def filter_timeline_by_dates(self, a: str, b: str) -> None:
        # The controls are <input type=datetime-local>; a bare date needs a midnight time.
        self._submit_filter(from_dt=f"{a}T00:00", to_dt=f"{b}T00:00")

    def _sort_state(self) -> tuple[str, str]:
        return (
            self.page.locator("[name='sort']").input_value(),
            self.page.locator("[name='dir']").input_value(),
        )

    def view_activity_by(self, grain: str) -> None:
        # Follow the grain toggle link above the chart — a real click, no URL crafting.
        self.open_timeline()
        with self.page.expect_navigation(wait_until="load"):
            self.page.locator(f"[data-grain-option='{grain}']").click()

    def sort_timeline(self, column: str, direction: str) -> None:
        # Follow the sortable column header link; one click toggles, so click until it lands on
        # the requested (column, direction).
        self.open_timeline()
        for _ in range(3):
            if self._sort_state() == (column, direction):
                return
            with self.page.expect_navigation(wait_until="load"):
                self.page.locator(f"[data-sort='{column}']").click()
        assert self._sort_state() == (column, direction), f"sort stuck at {self._sort_state()}"

    # ── export (follow the export link, read the download) ────────────────────
    def _download(self, link_name: str) -> None:
        # Export carries whatever filter the *current* page holds, so act on it in place.
        self._on_timeline()
        with self.page.expect_download() as dl:
            self.page.get_by_role("link", name=link_name).click()
        self._export_text = dl.value.path().read_text()

    def export_timeline_ndjson(self) -> None:
        self._download("Export NDJSON")

    def export_timeline_csv(self) -> None:
        self._download("Export CSV")

    # ── assertions (rendered DOM) ─────────────────────────────────────────────
    def _events(self) -> list[str]:
        # The selector guarantees the attribute is present, so `or ""` only satisfies the type.
        return [
            r.get_attribute("data-entry-name") or ""
            for r in self.page.locator("tr[data-entry-name]").all()
        ]

    def assert_timeline_empty(self) -> None:
        self.page.wait_for_selector("[data-timeline-empty]", timeout=5000)

    def assert_entry_listed(self, event: str) -> None:
        self.page.wait_for_selector(f"tr[data-entry-name='{event}']", timeout=5000)

    def assert_entry_not_listed(self, event: str) -> None:
        assert event not in self._events(), f"{event!r} unexpectedly listed in {self._events()}"

    def assert_entry_source(self, event: str, source: str) -> None:
        row = self.page.locator(f"tr[data-entry-name='{event}']").first
        assert row.count() > 0, f"{event!r} not listed: {self._events()}"
        actual = row.get_attribute("data-entry-source")
        assert actual == source, f"{event!r} source: expected {source!r}, got {actual!r}"

    def assert_entry_above(self, a: str, b: str) -> None:
        events = self._events()
        assert a in events, f"{a!r} not listed: {events}"
        assert b in events, f"{b!r} not listed: {events}"
        assert events.index(a) < events.index(b), f"{a!r} not above {b!r}: {events}"

    def assert_source_count(self, source: str, expected: int) -> None:
        n = self.page.locator(f"tr[data-entry-source='{source}']").count()
        assert n == expected, f"expected {expected} {source!r} entries, got {n}"

    def assert_all_listed(self, *events: str) -> None:
        listed = self._events()
        missing = [e for e in events if e not in listed]
        assert not missing, f"{missing!r} not all listed in {listed}"

    def assert_activity(self, date: str, business: int, http: int, error: int) -> None:
        raw = self.page.locator("[data-activity]").first.get_attribute("data-activity")
        act = json.loads(raw or "{}").get(date, {})
        assert act.get("business", 0) == business, f"activity {date} business: {act}"
        assert act.get("http", 0) == http, f"activity {date} http: {act}"
        assert act.get("error", 0) == error, f"activity {date} error: {act}"

    def assert_export_contains(self, needle: str) -> None:
        assert needle in self._export_text, f"{needle!r} not in export:\n{self._export_text}"

    def assert_export_excludes(self, needle: str) -> None:
        assert needle not in self._export_text, f"{needle!r} unexpectedly in export"

    def assert_csv_export(self, needle: str) -> None:
        lines = self._export_text.splitlines()
        assert lines, "empty CSV export"
        assert lines[0].split(",")[0] == "ts", f"expected header row, got {lines[0]!r}"
        assert any(needle in line for line in lines[1:]), f"{needle!r} not listed in CSV rows"

    # ── access ────────────────────────────────────────────────────────────────
    def try_open_timeline(self) -> None:
        probe = getattr(self, "_probe_blocked", None)  # organizations mixin
        assert probe is not None
        probe("GET", "/console/timeline")
