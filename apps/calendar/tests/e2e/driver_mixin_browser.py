import re

from tests.e2e.drivers.browser_base import BrowserBase


class CalendarBrowserMixin(BrowserBase):
    # ── helpers ────────────────────────────────────────────────────────────────
    def _cal_acting_handle(self) -> str:
        email = getattr(self, "_acting_email", "")
        return getattr(self, "secondary_handles", {}).get(email) or getattr(
            self, "active_org_handle", ""
        )

    def _cal_goto(self, handle: str | None = None) -> None:
        """Into the calendar by the sidebar entry — the only way in that a person has."""
        self.follow_org_nav(handle or getattr(self, "active_org_handle", ""), "calendar")

    def _cal_on(self, handle: str | None = None, *, fresh: bool = False) -> None:
        """On the calendar, without walking back to it when it is already the page shown.
        ``fresh`` for whoever reads the events off it, rather than only heading somewhere from
        there."""
        self.reach_org_nav(
            handle or getattr(self, "active_org_handle", ""), "calendar", fresh=fresh
        )

    def _cal_time_fields(self, start: str, end: str) -> dict[str, str]:
        start_date, start_time = start.split(" ")
        end_date, end_time = end.split(" ")
        return {
            "Start date": start_date,
            "Start time": start_time,
            "End date": end_date,
            "End time": end_time,
        }

    def _cal_open_new_form(self) -> None:
        self._cal_on()
        self.page.get_by_role("link", name="New event").click()
        self.page.get_by_label("Title").wait_for()

    def _cal_open_edit_form(self, title: str) -> None:
        self.open_event(title)
        self.page.get_by_role("link", name="Edit").click()
        self.page.get_by_label("Title").wait_for()

    def _cal_titles_on_page(self) -> list[str]:
        return [
            el.inner_text().strip() for el in self.page.locator("#event-list .event-title").all()
        ]

    def _cal_titles(self) -> list[str]:
        self._cal_on(self._cal_acting_handle(), fresh=True)
        return self._cal_titles_on_page()

    # ── given / actions ──────────────────────────────────────────────────────--
    def given_event(self, title: str, start: str, end: str) -> None:
        self.create_event(title, start, end)

    def create_event(self, title: str, start: str, end: str) -> None:
        self._cal_open_new_form()
        fields = {"Title": title, **self._cal_time_fields(start, end)}
        save = self.page.get_by_role("button", name="Save event")
        self.submit_labelled_form(self.page, fields, save)

    def create_event_full(
        self, title: str, start: str, end: str, location: str, description: str
    ) -> None:
        self._cal_open_new_form()
        fields = {
            "Title": title,
            **self._cal_time_fields(start, end),
            "Location": location,
            "Description": description,
        }
        save = self.page.get_by_role("button", name="Save event")
        self.submit_labelled_form(self.page, fields, save)

    def try_create_event(self, title: str | None, start: str, end: str) -> None:
        self._cal_open_new_form()
        # A single space satisfies the client-side `required` yet the server strips it to empty,
        # so the "no title" case still reaches the server-side 422 (true cross-driver parity).
        fields = {"Title": title if title is not None else " ", **self._cal_time_fields(start, end)}
        self.last_response = self.submit_labelled_form(
            self.page,
            fields,
            self.page.get_by_role("button", name="Save event"),
            method="POST",
            path_token="/calendar",
        )

    def open_event(self, title: str) -> None:
        # From the list as the server renders it now: the row clicked has to be the one the last
        # action left, and what the detail then shows is read as the stored event.
        self._cal_on(fresh=True)
        self.page.locator(
            "#event-list a.event-title", has_text=re.compile(rf"^{re.escape(title)}$")
        ).first.click()
        self.page.wait_for_selector("[data-when]")

    def rename_event(self, title: str, new_title: str) -> None:
        self._cal_open_edit_form(title)
        self.submit_labelled_form(
            self.page, {"Title": new_title}, self.page.get_by_role("button", name="Save event")
        )

    def reschedule_event(self, title: str, start: str, end: str) -> None:
        self._cal_open_edit_form(title)
        self.submit_labelled_form(
            self.page,
            self._cal_time_fields(start, end),
            self.page.get_by_role("button", name="Save event"),
        )

    def delete_event(self, title: str) -> None:
        self.open_event(title)
        self.page.once("dialog", lambda d: d.accept())
        with self.page.expect_navigation(wait_until="load"):
            self.page.get_by_role("button", name="Delete").click()

    def view_calendar(self) -> None:
        self._cal_on(fresh=True)

    def view_calendar_as(self, email: str) -> None:
        handle = getattr(self, "secondary_handles", {}).get(email) or getattr(
            self, "active_org_handle", ""
        )
        self.set_acting_email(email)
        self._cal_on(handle, fresh=True)

    # ── assertions ───────────────────────────────────────────────────────────--
    def assert_no_events(self) -> None:
        titles = self._cal_titles()
        assert titles == [], f"expected an empty calendar, got {titles}"

    def assert_event_order(self, titles: list[str]) -> None:
        actual = self._cal_titles()
        assert actual == titles, f"expected order {titles}, got {actual}"

    def assert_event_visible(self, title: str) -> None:
        titles = self._cal_titles()
        assert title in titles, f"'{title}' not found in calendar: {titles}"

    def assert_event_absent(self, title: str) -> None:
        titles = self._cal_titles()
        assert title not in titles, f"'{title}' should be absent but found in: {titles}"

    def assert_event_rejected(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status in (400, 422), (
            f"expected the event to be rejected, got {self.last_response.status}"
        )

    def assert_event_when(self, when: str) -> None:
        actual = self.page.locator("[data-when]").first.inner_text().strip()
        assert actual == when, f"expected when {when!r}, got {actual!r}"

    def assert_event_location(self, location: str) -> None:
        actual = self.page.locator("[data-location]").first.inner_text().strip()
        assert actual == location, f"expected location {location!r}, got {actual!r}"

    def assert_event_description(self, description: str) -> None:
        actual = self.page.locator("[data-description]").first.inner_text().strip()
        assert actual == description, f"expected description {description!r}, got {actual!r}"

    def assert_named_event_when(self, title: str, when: str) -> None:
        self.open_event(title)
        actual = self.page.locator("[data-when]").first.inner_text().strip()
        assert actual == when, f"expected when {when!r}, got {actual!r}"
