from apps.issues.infra.repository import record_occurrence
from tests.e2e.drivers.browser_base import BrowserBase


class IssuesBrowserMixin(BrowserBase):
    def seed_captured_error(self, title: str, count: int, version: str = "dev") -> None:
        seed = getattr(self, "_seed", None)  # learning mixin
        assert seed is not None

        async def _do(s):
            for _ in range(count):
                await record_occurrence(
                    s,
                    fingerprint=f"seed-{title}",
                    title=title,
                    version=version,
                    context={"stack": "Traceback: seeded", "request_id": "seed"},
                )

        seed(_do)

    def open_issues_screen(self) -> None:
        as_admin = getattr(self, "_as_admin", None)  # console mixin
        assert as_admin is not None
        as_admin()
        self.page.goto(f"{self.base_url}/console/issues", wait_until="load")

    def _issue_row(self, title: str):
        return self.page.locator("[data-issue]", has_text=title).first

    def open_issue_detail(self, title: str) -> None:
        self.open_issues_screen()
        self._issue_row(title).click()
        self.page.wait_for_selector("#triage", timeout=5000)

    def set_issue_status(self, title: str, status: str) -> None:
        self.open_issue_detail(title)
        button = {"resolved": "Resolve", "ignored": "Ignore"}[status]
        self.page.get_by_role("button", name=button).click()
        self.page.wait_for_selector(f"[data-status-badge]:has-text('{status}')", timeout=5000)

    def assert_issue_listed(self, title: str, status: str, count: int) -> None:
        self.open_issues_screen()
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
