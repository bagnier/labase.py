"""Locust perf smoke — one user class per context, all sharing one signed-in account.

Transport goes through Locust's client (that is what gets measured); request
bodies and response parsing go through the generated OpenAPI client
(``client/``, package ``labase-client``) — which keeps that client honest:
a route or DTO drift breaks the smoke run.

Run via ``make perf-smoke`` (scripts/perf_smoke.py boots the app on the test
schema and enforces the thresholds below as a blocking CI step).
"""

import uuid

import httpx
from labase_client.models import (
    BodyAddTodoOrgHandleTodosPost,
    OrganizationWithRoleRead,
)
from locust import HttpUser, between, events, task

_PASSWORD = "Perf1234!"

# Blocking thresholds (enforced on quit): a smoke, not a benchmark — generous
# enough for a loaded CI runner, tight enough to catch a real regression.
FAIL_RATIO_MAX = 0.01
P95_MS_MAX = 800.0

_account: dict = {}


@events.init.add_listener
def _create_account(environment, **_kwargs):
    """One real account for the whole swarm — register/login are rate-limited per IP."""
    email = f"perf-{uuid.uuid4().hex[:8]}@test.local"
    with httpx.Client(
        base_url=environment.host, headers={"accept": "application/json"}, timeout=30
    ) as client:
        client.post("/auth/register", json={"email": email, "password": _PASSWORD})
        response = client.post("/auth/login", json={"email": email, "password": _PASSWORD})
        response.raise_for_status()
        cookies = dict(client.cookies)
        orgs = client.get("/organizations").json()
    parsed = [OrganizationWithRoleRead.from_dict(o) for o in orgs]
    _account.update(cookies=cookies, org=parsed[0].handle)


@events.quitting.add_listener
def _enforce_thresholds(environment, **_kwargs):
    """The thresholds ARE the verdict — override Locust's any-failure exit code."""
    total = environment.stats.total
    p95 = total.get_response_time_percentile(0.95) or 0
    if total.fail_ratio > FAIL_RATIO_MAX:
        print(f"PERF SMOKE FAILED: fail ratio {total.fail_ratio:.2%} > {FAIL_RATIO_MAX:.0%}")
        environment.process_exit_code = 1
    elif p95 > P95_MS_MAX:
        print(f"PERF SMOKE FAILED: p95 {p95:.0f}ms > {P95_MS_MAX:.0f}ms")
        environment.process_exit_code = 1
    else:
        environment.process_exit_code = 0


class _SignedInUser(HttpUser):
    abstract = True
    wait_time = between(0.05, 0.2)

    def on_start(self):
        self.client.cookies.update(_account["cookies"])
        self.client.headers["accept"] = "application/json"
        self.org = _account["org"]


class TodoUser(_SignedInUser):
    @task(3)
    def list_todos(self):
        self.client.get(f"/{self.org}/todos", name="GET /{org}/todos")

    @task(1)
    def create_then_delete(self):
        body = BodyAddTodoOrgHandleTodosPost(title=f"perf {uuid.uuid4().hex[:6]}")
        with self.client.post(
            f"/{self.org}/todos",
            json=body.to_dict(),
            name="POST /{org}/todos",
            catch_response=True,
        ) as response:
            if response.status_code == 409:
                # Optimistic-concurrency conflict on the position column —
                # expected when the swarm writes one org; the client retries.
                response.success()
                return
        if response.ok:  # keep the org under max_items_per_org across runs
            todo_id = response.json()["id"]
            self.client.delete(f"/{self.org}/todos/{todo_id}", name="DELETE /{org}/todos/{id}")


class OrganizationsUser(_SignedInUser):
    @task
    def list_organizations(self):
        response = self.client.get("/organizations", name="GET /organizations")
        if response.ok:
            for item in response.json():
                OrganizationWithRoleRead.from_dict(item)  # DTO drift fails the smoke

    @task
    def dashboard_overviews(self):
        self.client.get(
            f"/{self.org}/dashboard/overviews.json", name="GET /{org}/dashboard/overviews.json"
        )


class PagesUser(_SignedInUser):
    @task
    def list_pages(self):
        self.client.get(f"/{self.org}/pages", name="GET /{org}/pages")
