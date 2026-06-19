from tests.e2e.drivers.api_base import ApiBase


class TodoApiMixin(ApiBase):
    def _todos_url(self, path: str = "") -> str:
        slug = getattr(self, "active_org_handle", "")
        return f"/{slug}/todos{path}"

    def _todo_id_by_title(self, title: str) -> str:
        resp = self.json_client("GET", self._todos_url())
        todos = resp.json()
        for t in todos:
            if t["title"] == title:
                return t["id"]
        raise AssertionError(f"Todo '{title}' not found in list")

    def have_todo_items(self, titles: list[str]) -> None:
        for title in reversed(titles):
            self.json_client("POST", self._todos_url(), json={"title": title})

    def view_todo_list(self) -> None:
        self.response = self.json_client("GET", self._todos_url())

    def add_todo(self, title: str) -> None:
        self.response = self.json_client("POST", self._todos_url(), json={"title": title})

    def mark_todo_done(self, title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self.response = self.json_client(
            "PATCH", self._todos_url(f"/{todo_id}"), json={"done": True}
        )

    def mark_todo_not_done(self, title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self.response = self.json_client(
            "PATCH", self._todos_url(f"/{todo_id}"), json={"done": False}
        )

    def rename_todo(self, title: str, new_title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self.response = self.json_client(
            "PATCH", self._todos_url(f"/{todo_id}"), json={"title": new_title}
        )

    def delete_todo(self, title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self.response = self.json_client("DELETE", self._todos_url(f"/{todo_id}"))

    def move_todo_above(self, title: str, above: str) -> None:
        resp = self.json_client("GET", self._todos_url())
        todos = resp.json()
        ids = {t["title"]: t["id"] for t in todos}
        self.response = self.json_client(
            "PUT", self._todos_url(f"/{ids[title]}/position"), json={"above_id": ids[above]}
        )

    def move_todo_to_end(self, title: str) -> None:
        resp = self.json_client("GET", self._todos_url())
        todos = resp.json()
        ids = {t["title"]: t["id"] for t in todos}
        self.response = self.json_client(
            "PUT", self._todos_url(f"/{ids[title]}/position"), json={"above_id": None}
        )

    def assert_todo_list_order(self, titles: list[str]) -> None:
        resp = self.json_client("GET", self._todos_url())
        actual = [t["title"] for t in resp.json()]
        assert actual == titles, f"Expected order {titles}, got {actual}"

    def assert_todo_visible(self, title: str) -> None:
        resp = self.json_client("GET", self._todos_url())
        titles = [t["title"] for t in resp.json()]
        assert title in titles, f"'{title}' not found in todo list: {titles}"

    def assert_todo_completed(self, title: str) -> None:
        resp = self.json_client("GET", self._todos_url())
        for t in resp.json():
            if t["title"] == title:
                assert t["done"], f"Todo '{title}' is not marked as done"
                return
        raise AssertionError(f"Todo '{title}' not found")

    def assert_todo_not_completed(self, title: str) -> None:
        resp = self.json_client("GET", self._todos_url())
        for t in resp.json():
            if t["title"] == title:
                assert not t["done"], f"Todo '{title}' should not be marked as done"
                return
        raise AssertionError(f"Todo '{title}' not found")

    def assert_todo_absent(self, title: str) -> None:
        resp = self.json_client("GET", self._todos_url())
        titles = [t["title"] for t in resp.json()]
        assert title not in titles, f"'{title}' should be absent but found in: {titles}"
