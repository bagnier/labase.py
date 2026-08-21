from apps.issues.infra.repository import see_occurrence
from tests.e2e.drivers.browser_base import BrowserBase


class IssuesBrowserMixin(BrowserBase):
    def seed_captured_error(self, title: str, count: int, version: str = "dev") -> None:
        seed = getattr(self, "_seed", None)  # learning mixin
        assert seed is not None

        async def _do(s):
            for _ in range(count):
                await see_occurrence(
                    s,
                    fingerprint=f"seed-{title}",
                    title=title,
                    version=version,
                    context={"stack": "Traceback: seeded", "request_id": "seed"},
                )

        seed(_do)

    def open_issues_screen(self) -> None:
        open_link = getattr(self, "open_console_link", None)  # console mixin
        assert open_link is not None
        open_link("/console/issues")

    def _issue_row(self, title: str):
        return self.page.locator("[data-issue]", has_text=title).first

    def _on_issues(self, *, fresh: bool = False) -> None:
        """On the issues list, without going round by the console when it is already open.
        ``fresh`` re-reads it: triage changes rows, and the row about to be clicked has to be
        the one the server holds."""
        self.be_on("/console/issues", self.open_issues_screen, fresh=fresh)

    def open_issue_detail(self, title: str) -> None:
        self._on_issues(fresh=True)
        self._issue_row(title).click()
        self.page.wait_for_selector("#triage", timeout=5000)

    def set_issue_status(self, title: str, status: str) -> None:
        self.open_issue_detail(title)
        button = {"resolved": "Resolve", "ignored": "Ignore"}[status]
        self.page.get_by_role("button", name=button).click()
        self.page.wait_for_selector(f"[data-status-badge]:has-text('{status}')", timeout=5000)

    def _back_to_the_list(self) -> None:
        """Triage leaves the admin on an issue's detail page; the way back to the list is the
        page's own link, which is also what a human would click."""
        back = self.page.get_by_role("link", name="← Issues")
        if back.count():
            back.click()
            self.page.wait_for_selector("[data-issue]", timeout=5000)

    def assert_issue_listed(self, title: str, status: str, count: int) -> None:
        self._back_to_the_list()
        row = self.page.locator(f"[data-issue-status='{status}']", has_text=title).first
        row.wait_for(timeout=5000)
        assert f"×{count}" in row.inner_text(), f"×{count} not in row: {row.inner_text()!r}"

    def assert_issue_detail_shows(self, count: int) -> None:
        assert self.page.locator("[data-issue-occurrence]").count() == count
        first = self.page.locator("[data-issue-occurrence]").first
        first.locator("summary").click()
        assert "Traceback" in first.locator("pre").inner_text()

    def try_open_issues_screen(self) -> None:
        probe = getattr(self, "_probe_blocked", None)  # organizations mixin
        assert probe is not None
        probe("GET", "/console/issues")
