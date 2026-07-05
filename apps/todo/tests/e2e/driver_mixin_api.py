from sqlalchemy import text

from tests.e2e.drivers import api_transaction as db
from tests.e2e.drivers.api_base import ApiBase


class TodoApiMixin(ApiBase):
    def _todos_url(self, path: str = "") -> str:
        slug = getattr(self, "active_org_handle", "")
        return f"/{slug}/todos{path}"

    def _todo_id_by_title(self, title: str) -> str:
        resp = self.client().get(self._todos_url())
        todos = resp.json()
        for t in todos:
            if t["title"] == title:
                return t["id"]
        raise AssertionError(f"Todo '{title}' not found in list")

    def have_todo_items(self, titles: list[str]) -> None:
        for title in reversed(titles):
            self.client().post(self._todos_url(), json={"title": title}).raise_for_status()

    def view_todo_list(self) -> None:
        self.client().get(self._todos_url()).raise_for_status()

    def add_todo(self, title: str) -> None:
        self.client().post(self._todos_url(), json={"title": title}).raise_for_status()

    def try_add_todo(self, title: str) -> None:
        self.response = self.client().post(self._todos_url(), json={"title": title})

    def seed_org_setting_override(self, app: str, key: str, value: str) -> None:
        resolve_org = getattr(self, "_active_org_id", None)  # provided by the learning mixin
        assert resolve_org is not None
        org_id = resolve_org()

        async def _do(s):
            await s.execute(
                text(
                    "INSERT INTO org_app_settings (app, key, org_id, value) "
                    "VALUES (:a, :k, :o, :v) "
                    "ON CONFLICT (app, key, org_id) DO UPDATE SET value = :v"
                ),
                {"a": app, "k": key, "o": org_id, "v": value},
            )

        self.run(db.seed_fixtures(_do))

    def mark_todo_done(self, title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self.client().patch(self._todos_url(f"/{todo_id}"), json={"done": True}).raise_for_status()

    def mark_todo_not_done(self, title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self.client().patch(self._todos_url(f"/{todo_id}"), json={"done": False}).raise_for_status()

    def rename_todo(self, title: str, new_title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        resp = self.client().patch(self._todos_url(f"/{todo_id}"), json={"title": new_title})
        resp.raise_for_status()

    def delete_todo(self, title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self.client().delete(self._todos_url(f"/{todo_id}")).raise_for_status()

    def move_todo_above(self, title: str, above: str) -> None:
        resp = self.client().get(self._todos_url())
        todos = resp.json()
        ids = {t["title"]: t["id"] for t in todos}
        self.client().put(
            self._todos_url(f"/{ids[title]}/position"), json={"above_id": ids[above]}
        ).raise_for_status()

    def move_todo_to_end(self, title: str) -> None:
        resp = self.client().get(self._todos_url())
        todos = resp.json()
        ids = {t["title"]: t["id"] for t in todos}
        self.client().put(
            self._todos_url(f"/{ids[title]}/position"), json={"above_id": None}
        ).raise_for_status()

    def assert_todo_list_order(self, titles: list[str]) -> None:
        resp = self.client().get(self._todos_url())
        actual = [t["title"] for t in resp.json()]
        assert actual == titles, f"Expected order {titles}, got {actual}"

    def assert_todo_visible(self, title: str) -> None:
        resp = self.client().get(self._todos_url())
        titles = [t["title"] for t in resp.json()]
        assert title in titles, f"'{title}' not found in todo list: {titles}"

    def assert_todo_completed(self, title: str) -> None:
        resp = self.client().get(self._todos_url())
        for t in resp.json():
            if t["title"] == title:
                assert t["done"], f"Todo '{title}' is not marked as done"
                return
        raise AssertionError(f"Todo '{title}' not found")

    def assert_todo_not_completed(self, title: str) -> None:
        resp = self.client().get(self._todos_url())
        for t in resp.json():
            if t["title"] == title:
                assert not t["done"], f"Todo '{title}' should not be marked as done"
                return
        raise AssertionError(f"Todo '{title}' not found")

    def assert_todo_absent(self, title: str) -> None:
        resp = self.client().get(self._todos_url())
        titles = [t["title"] for t in resp.json()]
        assert title not in titles, f"'{title}' should be absent but found in: {titles}"
