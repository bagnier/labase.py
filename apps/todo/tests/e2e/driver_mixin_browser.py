from sqlalchemy import text

from tests.e2e.drivers.browser_base import BrowserBase


class TodoBrowserMixin(BrowserBase):
    def _todos_url(self) -> str:
        slug = getattr(self, "active_org_handle", "")
        return f"{self.base_url}/{slug}/todos"

    def _dom_todo_rows(self) -> list:
        return self.page.locator("#todo-list > li").all()

    def _dom_todo_titles(self) -> list[str]:
        return [
            row.locator("[data-title-id]").inner_text().strip() for row in self._dom_todo_rows()
        ]

    def _dom_todo_id_by_title(self, title: str) -> str:
        row = self.find_row(self.page, "#todo-list > li", "[data-title-id]", title)
        return row.locator("input[data-todo-id]").get_attribute("data-todo-id") or ""

    def have_todo_items(self, titles: list[str]) -> None:
        for title in reversed(titles):
            self.add_todo(title)

    def view_todo_list(self) -> None:
        self.last_response = self.page.goto(self._todos_url(), wait_until="load")

    def _goto_todos(self) -> None:
        self.page.goto(self._todos_url(), wait_until="load")

    def try_add_todo(self, title: str) -> None:
        # HTMX drops 4xx swaps; fire the request the form would send and keep the
        # response so "the action is forbidden" asserts server-side enforcement.
        slug = getattr(self, "active_org_handle", "")
        probe = getattr(self, "_probe_blocked", None)  # provided by the organizations mixin
        assert probe is not None
        probe("POST", f"/{slug}/todos", form={"title": title})

    def seed_org_setting_override(self, app: str, key: str, value: str) -> None:
        resolve_org = getattr(self, "_active_org_id", None)  # learning mixin
        seed = getattr(self, "_seed", None)  # learning mixin
        assert resolve_org is not None and seed is not None
        org_id = resolve_org()
        seed(
            lambda s: s.execute(
                text(
                    "INSERT INTO org_app_settings (app, key, org_id, value) "
                    "VALUES (:a, :k, :o, :v) "
                    "ON CONFLICT (app, key, org_id) DO UPDATE SET value = :v"
                ),
                {"a": app, "k": key, "o": str(org_id), "v": value},
            )
        )

    def add_todo(self, title: str) -> None:
        self._goto_todos()
        form_path = f"/{getattr(self, 'active_org_handle', '')}/todos"
        self.submit_labelled_form(
            self.page,
            {"New todo": title},
            self.page.get_by_role("button", name="Add"),
            method="POST",
            path_token=form_path,
        )
        self._goto_todos()

    def mark_todo_done(self, title: str) -> None:
        self._goto_todos()
        todo_id = self._dom_todo_id_by_title(title)
        self.row_action(
            self.page,
            "#todo-list > li",
            "[data-title-id]",
            title,
            f"input[data-todo-id='{todo_id}']",
            "PATCH",
            f"/todos/{todo_id}",
        )
        self._goto_todos()

    def mark_todo_not_done(self, title: str) -> None:
        self.mark_todo_done(title)

    def rename_todo(self, title: str, new_title: str) -> None:
        self._goto_todos()
        todo_id = self._dom_todo_id_by_title(title)
        self.page.evaluate(f"startEdit('{todo_id}')")
        form_input = self.page.locator(f"#rename-form-{todo_id} input[name=title]")
        form_input.wait_for(state="visible", timeout=5000)
        form_input.fill(new_title)
        self.wait_htmx(self.page, "PATCH", f"/todos/{todo_id}", lambda: form_input.press("Enter"))
        self._goto_todos()

    def delete_todo(self, title: str) -> None:
        self._goto_todos()
        todo_id = self._dom_todo_id_by_title(title)
        self.row_action(
            self.page,
            "#todo-list > li",
            "[data-title-id]",
            title,
            f"button[data-delete-id='{todo_id}']",
            "DELETE",
            f"/todos/{todo_id}",
        )
        self._goto_todos()

    def move_todo_above(self, title: str, above: str) -> None:
        self.page.goto(self._todos_url(), wait_until="load")
        source_id = self._dom_todo_id_by_title(title)
        target_id = self._dom_todo_id_by_title(above)
        slug = getattr(self, "active_org_handle", "")
        url = f"/{slug}/todos/{source_id}/position"
        with self.page.expect_response(
            lambda r: f"/todos/{source_id}/position" in r.url and r.request.method == "PUT"
        ):
            self.page.evaluate(
                """([url, above_id]) => fetch(url, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({above_id})
                })""",
                [url, target_id],
            )
        self.page.goto(self._todos_url(), wait_until="load")

    def move_todo_to_end(self, title: str) -> None:
        self.page.goto(self._todos_url(), wait_until="load")
        source_id = self._dom_todo_id_by_title(title)
        rows = self._dom_todo_rows()
        last_row = rows[-1]
        source = f".todo-item:has(input[data-todo-id='{source_id}']) .drag-handle"
        with self.page.expect_response(
            lambda r: f"/todos/{source_id}/position" in r.url and r.request.method == "PUT"
        ):
            self.page.locator(source).drag_to(last_row, target_position={"x": 10, "y": 40})
        self.page.goto(self._todos_url(), wait_until="load")

    def assert_todo_list_order(self, titles: list[str]) -> None:
        actual = self._dom_todo_titles()
        assert actual == titles, f"Expected order {titles}, got {actual}"

    def assert_todo_visible(self, title: str) -> None:
        titles = self._dom_todo_titles()
        assert title in titles, f"'{title}' not found in #todo-list DOM: {titles}"

    def assert_todo_completed(self, title: str) -> None:
        for row in self._dom_todo_rows():
            if row.locator("[data-title-id]").inner_text().strip() == title:
                assert row.locator("input[data-todo-id]").is_checked(), (
                    f"Todo '{title}' is not shown as completed in DOM"
                )
                return
        raise AssertionError(f"Todo '{title}' not found in DOM")

    def assert_todo_not_completed(self, title: str) -> None:
        for row in self._dom_todo_rows():
            if row.locator("[data-title-id]").inner_text().strip() == title:
                assert not row.locator("input[data-todo-id]").is_checked(), (
                    f"Todo '{title}' is shown as completed in DOM"
                )
                return
        raise AssertionError(f"Todo '{title}' not found in DOM")

    def assert_todo_absent(self, title: str) -> None:
        titles = self._dom_todo_titles()
        assert title not in titles, (
            f"'{title}' should be absent but found in #todo-list DOM: {titles}"
        )
