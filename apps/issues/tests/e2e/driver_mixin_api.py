from apps.issues.infra.repository import record_occurrence
from tests.e2e.drivers import api_transaction as db
from tests.e2e.drivers.api_base import ApiBase


class IssuesApiMixin(ApiBase):
    def seed_captured_error(self, title: str, count: int, version: str = "dev") -> None:
        async def _do(s):
            for _ in range(count):
                await record_occurrence(
                    s,
                    fingerprint=f"seed-{title}",
                    title=title,
                    version=version,
                    context={"stack": "Traceback: seeded", "request_id": "seed"},
                )

        self.run(db.seed_fixtures(_do))

    def open_issues_screen(self) -> None:
        self._issues_as_admin()
        self.response = self.client().get("/console/issues", headers={"accept": "application/json"})

    def _issues_as_admin(self) -> None:
        as_admin = getattr(self, "_as_admin", None)  # console mixin
        assert as_admin is not None
        as_admin()

    def _issue_by_title(self, title: str) -> dict:
        resp = self.client().get("/console/issues", headers={"accept": "application/json"})
        assert resp.status_code == 200, f"GET issues: {resp.status_code} {resp.text}"
        issue = next((g for g in resp.json() if g["title"] == title), None)
        assert issue is not None, f"no issue titled {title!r}: {resp.json()}"
        return issue

    def set_issue_status(self, title: str, status: str) -> None:
        self._issues_as_admin()
        issue = self._issue_by_title(title)
        resp = self.client().post(f"/console/issues/{issue['id']}/status", json={"status": status})
        assert resp.status_code == 200, f"set status: {resp.status_code} {resp.text}"

    def assert_issue_listed(self, title: str, status: str, count: int) -> None:
        self._issues_as_admin()
        issue = self._issue_by_title(title)
        assert issue["status"] == status, f"expected {status!r}, got {issue['status']!r}"
        assert issue["count"] == count, f"expected ×{count}, got ×{issue['count']}"

    def open_issue_detail(self, title: str) -> None:
        self._issues_as_admin()
        issue = self._issue_by_title(title)
        self.response = self.client().get(
            f"/console/issues/{issue['id']}", headers={"accept": "application/json"}
        )
        assert self.response.status_code == 200

    def assert_issue_detail_shows(self, count: int) -> None:
        detail = self.response.json()
        occurrences = detail["occurrences"]
        assert len(occurrences) == count, f"expected {count} occurrences, got {len(occurrences)}"
        assert all("stack" in o["context"] for o in occurrences)

    def try_open_issues_screen(self) -> None:
        self.response = self.client().get("/console/issues", headers={"accept": "application/json"})
