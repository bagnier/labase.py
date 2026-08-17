from tests.e2e.drivers.api_base import ApiBase


class CalendarApiMixin(ApiBase):
    def reset_session(self) -> None:
        self._cal_events: list[dict] | None = None
        self._cal_detail: dict | None = None
        super().reset_session()

    # ── helpers ────────────────────────────────────────────────────────────────
    def _cal_url(self, path: str = "", handle: str | None = None) -> str:
        h = handle or getattr(self, "active_org_handle", "")
        return f"/{h}/calendar{path}"

    def _cal_acting_handle(self) -> str:
        email = getattr(self, "_acting_email", "")
        return getattr(self, "secondary_handles", {}).get(email, "") or getattr(
            self, "active_org_handle", ""
        )

    def _cal_list(self, handle: str | None = None) -> list[dict]:
        resp = self.client().get(self._cal_url(handle=handle))
        assert resp.status_code == 200, f"list calendar got {resp.status_code}: {resp.text}"
        return resp.json()

    def _cal_event_id(self, title: str) -> str:
        for e in self._cal_list():
            if e["title"] == title:
                return e["id"]
        raise AssertionError(f"Event '{title}' not found in calendar")

    def _cal_current(self) -> list[dict]:
        if self._cal_events is not None:
            events = self._cal_events
            self._cal_events = None
            return events
        return self._cal_list()

    # ── given / actions ──────────────────────────────────────────────────────--
    def given_event(self, title: str, start: str, end: str) -> None:
        resp = self.client().post(
            self._cal_url(), json={"title": title, "start": start, "end": end}
        )
        resp.raise_for_status()

    def create_event(self, title: str, start: str, end: str) -> None:
        self.response = self.client().post(
            self._cal_url(), json={"title": title, "start": start, "end": end}
        )
        self.response.raise_for_status()

    def create_event_full(
        self, title: str, start: str, end: str, location: str, description: str
    ) -> None:
        self.response = self.client().post(
            self._cal_url(),
            json={
                "title": title,
                "start": start,
                "end": end,
                "location": location,
                "description": description,
            },
        )
        self.response.raise_for_status()

    def try_create_event(self, title: str | None, start: str, end: str) -> None:
        payload: dict = {"start": start, "end": end}
        if title is not None:
            payload["title"] = title
        self.response = self.client().post(self._cal_url(), json=payload)

    def open_event(self, title: str) -> None:
        resp = self.client().get(self._cal_url(f"/{self._cal_event_id(title)}"))
        assert resp.status_code == 200, f"open event got {resp.status_code}: {resp.text}"
        self._cal_detail = resp.json()

    def rename_event(self, title: str, new_title: str) -> None:
        self.client().patch(
            self._cal_url(f"/{self._cal_event_id(title)}"), json={"title": new_title}
        ).raise_for_status()

    def reschedule_event(self, title: str, start: str, end: str) -> None:
        self.client().patch(
            self._cal_url(f"/{self._cal_event_id(title)}"), json={"start": start, "end": end}
        ).raise_for_status()

    def delete_event(self, title: str) -> None:
        self.client().delete(self._cal_url(f"/{self._cal_event_id(title)}")).raise_for_status()

    def view_calendar(self) -> None:
        self._cal_events = self._cal_list()

    def view_calendar_as(self, email: str) -> None:
        handle = getattr(self, "secondary_handles", {}).get(email) or getattr(
            self, "active_org_handle", ""
        )
        resp = self.client_for(email).get(self._cal_url(handle=handle))
        assert resp.status_code == 200, f"view as {email} got {resp.status_code}: {resp.text}"
        self._cal_events = resp.json()

    # ── assertions ───────────────────────────────────────────────────────────--
    def assert_no_events(self) -> None:
        events = self._cal_current()
        assert events == [], f"expected an empty calendar, got {[e['title'] for e in events]}"

    def assert_event_order(self, titles: list[str]) -> None:
        actual = [e["title"] for e in self._cal_current()]
        assert actual == titles, f"expected order {titles}, got {actual}"

    def assert_event_visible(self, title: str) -> None:
        titles = [e["title"] for e in self._cal_list()]
        assert title in titles, f"'{title}' not found in calendar: {titles}"

    def assert_event_absent(self, title: str) -> None:
        titles = [e["title"] for e in self._cal_current()]
        assert title not in titles, f"'{title}' should be absent but found in: {titles}"

    def assert_event_rejected(self) -> None:
        assert self.response.status_code in (400, 422), (
            f"expected rejection, got {self.response.status_code}: {self.response.text}"
        )

    def assert_event_when(self, when: str) -> None:
        assert self._cal_detail is not None, "open the event first"
        assert self._cal_detail["when"] == when, (
            f"expected when {when!r}, got {self._cal_detail.get('when')!r}"
        )

    def assert_event_location(self, location: str) -> None:
        assert self._cal_detail is not None, "open the event first"
        assert self._cal_detail["location"] == location, (
            f"expected location {location!r}, got {self._cal_detail.get('location')!r}"
        )

    def assert_event_description(self, description: str) -> None:
        assert self._cal_detail is not None, "open the event first"
        assert self._cal_detail["description"] == description, (
            f"expected description {description!r}, got {self._cal_detail.get('description')!r}"
        )

    def assert_named_event_when(self, title: str, when: str) -> None:
        resp = self.client().get(self._cal_url(f"/{self._cal_event_id(title)}"))
        assert resp.status_code == 200, f"open event got {resp.status_code}: {resp.text}"
        assert resp.json()["when"] == when, f"expected when {when!r}, got {resp.json()['when']!r}"
