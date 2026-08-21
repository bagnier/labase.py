import json
from datetime import datetime

from apps.shared import clock
from apps.shared.events.models import BusinessEventRecord
from apps.shared.logs.chain import apply_log_level
from apps.shared.logs.repository import LogRepository
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

    def seed_many_events(self, count: int, org: str) -> None:
        """A run of facts long enough to overflow one page — added in a single transaction, since
        a hundred round trips would be the slowest arrangement in the suite."""
        models = seed_data.event_run(count, timeline_org_id(org), now=clock.now())

        async def _do(s):
            s.add_all(models)

        self._run_seed(_do)

    def seed_event_by_user(self, event: str, email: str) -> None:
        self._add_event(seed_data.event_model(event, user=timeline_user_id(email)))

    def seed_event_about(self, event: str, org: str, subject: str) -> None:
        """A fact whose subject has a readable name — a todo's title, an org's. What the journal
        pins at write time and the timeline has to be searchable by."""
        self._add_event(seed_data.event_model(event, org=timeline_org_id(org), entity_name=subject))

    def _append_log(self, line: dict) -> None:
        """Straight into the store, bypassing the live level gate the runtime path is subject to
        (a seeded 'info' line must survive a WARNING process level)."""

        async def _do(s):
            await LogRepository(s).append([line], instance="test")

        self._run_seed(_do)

    def seed_request_from_org(
        self, event: str, org: str, *, level: str = "info", when: datetime | None = None
    ) -> None:
        self._append_log(
            seed_data.log_line(event, org=timeline_org_id(org), level=level, when=when)
        )

    def seed_error_from_org(self, title: str, org: str, *, when: datetime | None = None) -> None:
        self._insert_error(title, org=timeline_org_id(org), when=when)

    def set_process_log_level(self, level: str) -> None:
        # The browser app runs in-process, so this is the live log level.
        apply_log_level(level)

    def seed_correlated_request(
        self, request_id: str, org: str, event: str, error: str, *, when: datetime | None = None
    ) -> None:
        # All three sources must key on the same value for the timeline to correlate them.
        oid, request_id = timeline_org_id(org), timeline_request_id(request_id)
        self._append_log(
            seed_data.log_line("request.finished", org=oid, request_id=request_id, when=when)
        )
        self._add_event(seed_data.event_model(event, org=oid, request_id=request_id, when=when))
        self._insert_error(error, org=oid, request_id=request_id, when=when)

    # ── navigation / filters (follow links, submit the real form) ─────────────
    def open_timeline(self) -> None:
        open_link = getattr(self, "open_console_link", None)  # console mixin
        assert open_link is not None
        self.last_response = open_link("/console/timeline")

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

    # ── paging ───────────────────────────────────────────────────────────────
    def _subjects(self) -> list[str]:
        """What each visible row is *about*. A run of facts shares one kind, so the name column
        cannot tell one page's rows from the next one's — the subject can."""
        return [
            cell.strip() for cell in self.page.locator("[data-entry-entity]").all_text_contents()
        ]

    def load_older_entries(self) -> None:
        """Click the button and wait for what it loaded — no URL crafting."""
        self._on_timeline()
        self._first_page = self._subjects()
        self.page.locator("[data-load-more] button").click()
        # The row swaps itself out for the next batch, so the row count is what separates a
        # finished click from a request still in flight.
        self.page.wait_for_function(
            "n => document.querySelectorAll('[data-entry-entity]').length > n",
            arg=len(self._first_page),
        )

    def assert_offers_older_entries(self) -> None:
        assert self.page.locator("[data-load-more]").count() == 1, (
            "expected the timeline to offer a next page"
        )

    def assert_older_entries_do_not_repeat(self) -> None:
        added = self._subjects()[len(self._first_page) :]
        assert added, "the second page came back empty"
        assert not set(added) & set(self._first_page), "the second page repeats the first"

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

    def assert_source_count(self, source: str, expected: int, org: str) -> None:
        """How many of *this org's* rows one source contributed — read off the org cell's own
        correlation link, which is the only ``org_id=`` href on a row.

        Scoped, and not optionally: the store is shared with the running app, which writes its own
        ``request.finished`` for every page this driver loads. An exhaustive count therefore raced
        the log drain — the same assertion saw 1, 2 or 4 depending on when the batch landed.
        """
        rows = f"tr[data-entry-source='{source}']:has(a[href*='org_id={timeline_org_id(org)}'])"
        n = self.page.locator(rows).count()
        assert n == expected, f"expected {expected} {source!r} entries for {org!r}, got {n}"

    def assert_all_listed(self, *events: str) -> None:
        listed = self._events()
        missing = [e for e in events if e not in listed]
        assert not missing, f"{missing!r} not all listed in {listed}"

    def assert_activity(self, date: str, business: int, logs: int, issue: int) -> None:
        """What the reader sees: the on-screen legend, in series order, against the bars drawn
        for that bucket. Read from ``[data-chart-config]`` — the very JSON charts.js draws
        from — so a source renamed on one side alone shows up here instead of silently
        flattening a series to zero."""
        config = json.loads(self.page.locator("[data-chart-config]").first.text_content() or "{}")
        # A column's label is always a fragment of its bucket key ("06-26" of "2026-06-26",
        # "W26" of "2026-W26"), so the column is found without re-deriving the axis format.
        labels = config["options"]["xaxis"]["categories"]
        column = next(i for i, label in enumerate(labels) if label in date)
        legend = self.page.locator("[data-activity-legend] [data-legend-label]").all_text_contents()
        drawn = dict(zip(legend, [s["data"][column] for s in config["series"]], strict=True))
        assert drawn == {"Logs": logs, "Business": business, "Issue": issue}

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
