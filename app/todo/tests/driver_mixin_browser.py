from collections.abc import Callable

from tests.e2e.drivers.protocols import BrowserProtocol


class TodoBrowserMixin(BrowserProtocol):
    def _todos_url(self) -> str:
        slug = getattr(self, "_active_org_slug", "")
        return f"{self._base_url}/orgs/{slug}/todos"

    def _dom_todo_rows(self) -> list:
        return self._p.locator("#todo-list > div").all()

    def _dom_todo_titles(self) -> list[str]:
        return [row.locator("span.flex-1").inner_text().strip() for row in self._dom_todo_rows()]

    def _dom_todo_id_by_title(self, title: str) -> str:
        for row in self._dom_todo_rows():
            if row.locator("span.flex-1").inner_text().strip() == title:
                return row.locator("input[data-todo-id]").get_attribute("data-todo-id") or ""
        raise AssertionError(f"Todo '{title}' not found in DOM")

    def _api_todo_ids(self) -> dict[str, str]:
        assert self._context
        resp = self._context.request.get(
            self._todos_url(),
            headers={"accept": "application/json"},
        )
        return {t["title"]: t["id"] for t in resp.json()}

    def have_todo_items(self, titles: list[str]) -> None:
        assert self._context
        for title in reversed(titles):
            self._context.request.post(
                self._todos_url(),
                form={"title": title},
            )

    def view_todo_list(self) -> None:
        self._last_response = self._p.goto(self._todos_url(), wait_until="load")

    def _goto_todos(self) -> None:
        self._p.goto(self._todos_url(), wait_until="load")

    def _wait_htmx_response(self, url_fragment: str, method: str, action: Callable) -> None:
        with self._p.expect_response(
            lambda r: url_fragment in r.url and r.request.method == method, timeout=10000
        ):
            action()
        self._goto_todos()

    def add_todo(self, title: str) -> None:
        self._goto_todos()
        self._p.fill("input[name=title]", title)
        todos_path = f"/orgs/{getattr(self, '_active_org_slug', '')}/todos"
        self._wait_htmx_response(
            todos_path,
            "POST",
            lambda: self._p.locator(f"form[hx-post='{todos_path}'] button[type=submit]").click(),
        )

    def mark_todo_done(self, title: str) -> None:
        self._goto_todos()
        todo_id = self._dom_todo_id_by_title(title)
        self._wait_htmx_response(
            f"/todos/{todo_id}",
            "PATCH",
            lambda: self._p.click(f"input[data-todo-id='{todo_id}']"),
        )

    def rename_todo(self, title: str, new_title: str) -> None:
        self._goto_todos()
        todo_id = self._dom_todo_id_by_title(title)
        assert self._context
        self._context.request.patch(
            f"{self._todos_url()}/{todo_id}",
            form={"title": new_title},
        )
        self._goto_todos()

    def delete_todo(self, title: str) -> None:
        self._goto_todos()
        todo_id = self._dom_todo_id_by_title(title)
        self._p.once("dialog", lambda d: d.accept())
        self._wait_htmx_response(
            f"/todos/{todo_id}",
            "DELETE",
            lambda: self._p.click(f"button[data-delete-id='{todo_id}']"),
        )

    def move_todo_above(self, title: str, above: str) -> None:
        self._p.goto(self._todos_url(), wait_until="load")
        ids = {t: self._dom_todo_id_by_title(t) for t in (title, above)}
        assert self._context
        self._context.request.post(
            f"{self._todos_url()}/reorder",
            data={"id": ids[title], "above_id": ids[above]},
        )
        self._p.goto(self._todos_url(), wait_until="load")

    def move_todo_to_end(self, title: str) -> None:
        self._p.goto(self._todos_url(), wait_until="load")
        todo_id = self._dom_todo_id_by_title(title)
        assert self._context
        self._context.request.post(
            f"{self._todos_url()}/reorder",
            data={"id": todo_id},
        )
        self._p.goto(self._todos_url(), wait_until="load")

    def assert_todo_list_order(self, titles: list[str]) -> None:
        actual = self._dom_todo_titles()
        assert actual == titles, f"Expected order {titles}, got {actual}"

    def assert_todo_visible(self, title: str) -> None:
        titles = self._dom_todo_titles()
        assert title in titles, f"'{title}' not found in #todo-list DOM: {titles}"

    def assert_todo_completed(self, title: str) -> None:
        for row in self._dom_todo_rows():
            if row.locator("span.flex-1").inner_text().strip() == title:
                span = row.locator("span.flex-1")
                classes = span.get_attribute("class") or ""
                assert "line-through" in classes, f"Todo '{title}' is not shown as completed in DOM"
                return
        raise AssertionError(f"Todo '{title}' not found in DOM")

    def assert_todo_absent(self, title: str) -> None:
        titles = self._dom_todo_titles()
        assert title not in titles, (
            f"'{title}' should be absent but found in #todo-list DOM: {titles}"
        )
