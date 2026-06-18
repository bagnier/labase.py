from collections.abc import Callable

from tests.e2e.drivers.protocols import BrowserProtocol


class TodoBrowserMixin(BrowserProtocol):
    def _todos_url(self) -> str:
        slug = getattr(self, "_active_org_handle", "")
        return f"{self._base_url}/{slug}/todos"

    def _dom_todo_rows(self) -> list:
        return self._p.locator("#todo-list > div").all()

    def _dom_todo_titles(self) -> list[str]:
        return [row.locator("span.flex-1").inner_text().strip() for row in self._dom_todo_rows()]

    def _dom_todo_id_by_title(self, title: str) -> str:
        for row in self._dom_todo_rows():
            if row.locator("span.flex-1").inner_text().strip() == title:
                return row.locator("input[data-todo-id]").get_attribute("data-todo-id") or ""
        raise AssertionError(f"Todo '{title}' not found in DOM")

    def have_todo_items(self, titles: list[str]) -> None:
        for title in reversed(titles):
            self.add_todo(title)

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
        form_path = f"/{getattr(self, '_active_org_handle', '')}/todos"
        self._wait_htmx_response(
            form_path,
            "POST",
            lambda: self._p.locator(f"form[hx-post='{form_path}'] button[type=submit]").click(),
        )

    def mark_todo_done(self, title: str) -> None:
        self._goto_todos()
        todo_id = self._dom_todo_id_by_title(title)
        self._wait_htmx_response(
            f"/todos/{todo_id}",
            "PATCH",
            lambda: self._p.click(f"input[data-todo-id='{todo_id}']"),
        )

    def mark_todo_not_done(self, title: str) -> None:
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
        self._p.click(f"[data-edit-id='{todo_id}']")
        form_input = self._p.locator(f"#rename-form-{todo_id} input[name=title]")
        form_input.fill(new_title)
        self._wait_htmx_response(f"/todos/{todo_id}", "PATCH", lambda: form_input.press("Enter"))

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
        source_id = self._dom_todo_id_by_title(title)
        target_id = self._dom_todo_id_by_title(above)
        slug = getattr(self, "_active_org_handle", "")
        url = f"/{slug}/todos/{source_id}/position"
        with self._p.expect_response(
            lambda r: f"/todos/{source_id}/position" in r.url and r.request.method == "PUT"
        ):
            self._p.evaluate(
                """([url, above_id]) => fetch(url, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({above_id})
                })""",
                [url, target_id],
            )
        self._p.goto(self._todos_url(), wait_until="load")

    def move_todo_to_end(self, title: str) -> None:
        self._p.goto(self._todos_url(), wait_until="load")
        source_id = self._dom_todo_id_by_title(title)
        rows = self._dom_todo_rows()
        last_row = rows[-1]
        source = f".todo-item:has(input[data-todo-id='{source_id}']) .drag-handle"
        with self._p.expect_response(
            lambda r: f"/todos/{source_id}/position" in r.url and r.request.method == "PUT"
        ):
            self._p.locator(source).drag_to(last_row, target_position={"x": 10, "y": 40})
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

    def assert_todo_not_completed(self, title: str) -> None:
        for row in self._dom_todo_rows():
            if row.locator("span.flex-1").inner_text().strip() == title:
                span = row.locator("span.flex-1")
                classes = span.get_attribute("class") or ""
                assert "line-through" not in classes, f"Todo '{title}' is shown as completed in DOM"
                return
        raise AssertionError(f"Todo '{title}' not found in DOM")

    def assert_todo_absent(self, title: str) -> None:
        titles = self._dom_todo_titles()
        assert title not in titles, (
            f"'{title}' should be absent but found in #todo-list DOM: {titles}"
        )
