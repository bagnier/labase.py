from tests.e2e.drivers.protocols import ApiProtocol


class TodoApiMixin(ApiProtocol):
    def _todos_url(self, path: str = "") -> str:
        slug = getattr(self, "_active_org_slug", "")
        return f"/orgs/{slug}/todos{path}"

    def _todo_id_by_title(self, title: str) -> str:
        resp = self._run(self._c.get(self._todos_url(), headers={"accept": "application/json"}))
        todos = resp.json()
        for t in todos:
            if t["title"] == title:
                return t["id"]
        raise AssertionError(f"Todo '{title}' not found in list")

    def have_todo_items(self, titles: list[str]) -> None:
        for title in reversed(titles):
            self._run(self._c.post(self._todos_url(), data={"title": title}))

    def view_todo_list(self) -> None:
        self._response = self._run(self._c.get(self._todos_url()))

    def add_todo(self, title: str) -> None:
        self._response = self._run(self._c.post(self._todos_url(), data={"title": title}))

    def mark_todo_done(self, title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self._response = self._run(
            self._c.patch(self._todos_url(f"/{todo_id}"), data={"done": "true"})
        )

    def rename_todo(self, title: str, new_title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self._response = self._run(
            self._c.patch(self._todos_url(f"/{todo_id}"), data={"title": new_title})
        )

    def delete_todo(self, title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self._response = self._run(self._c.delete(self._todos_url(f"/{todo_id}")))

    def move_todo_above(self, title: str, above: str) -> None:
        resp = self._run(self._c.get(self._todos_url(), headers={"accept": "application/json"}))
        todos = resp.json()
        ids = {t["title"]: t["id"] for t in todos}
        self._response = self._run(
            self._c.post(
                self._todos_url("/reorder"), json={"id": ids[title], "above_id": ids[above]}
            )
        )

    def move_todo_to_end(self, title: str) -> None:
        resp = self._run(self._c.get(self._todos_url(), headers={"accept": "application/json"}))
        todos = resp.json()
        ids = {t["title"]: t["id"] for t in todos}
        self._response = self._run(
            self._c.post(self._todos_url("/reorder"), json={"id": ids[title], "above_id": None})
        )

    def assert_todo_list_order(self, titles: list[str]) -> None:
        resp = self._run(self._c.get(self._todos_url(), headers={"accept": "application/json"}))
        actual = [t["title"] for t in resp.json()]
        assert actual == titles, f"Expected order {titles}, got {actual}"

    def assert_todo_visible(self, title: str) -> None:
        resp = self._run(self._c.get(self._todos_url(), headers={"accept": "application/json"}))
        titles = [t["title"] for t in resp.json()]
        assert title in titles, f"'{title}' not found in todo list: {titles}"

    def assert_todo_completed(self, title: str) -> None:
        resp = self._run(self._c.get(self._todos_url(), headers={"accept": "application/json"}))
        for t in resp.json():
            if t["title"] == title:
                assert t["done"], f"Todo '{title}' is not marked as done"
                return
        raise AssertionError(f"Todo '{title}' not found")

    def assert_todo_absent(self, title: str) -> None:
        resp = self._run(self._c.get(self._todos_url(), headers={"accept": "application/json"}))
        titles = [t["title"] for t in resp.json()]
        assert title not in titles, f"'{title}' should be absent but found in: {titles}"
