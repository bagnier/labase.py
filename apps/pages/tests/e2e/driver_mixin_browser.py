from tests.e2e.drivers.browser_base import _VISITOR, BrowserBase


def _decode(content: str) -> str:
    return content.replace("\\n", "\n")


class PagesBrowserMixin(BrowserBase):
    def _handle(self) -> str:
        return getattr(self, "active_org_handle", "")

    def _pages_url(self, path: str = "", handle: str | None = None) -> str:
        return f"{self.base_url}/{handle or self._handle()}/pages{path}"

    def _fetch(self, method: str, path: str, body: dict | None = None):
        resp = self.page.request.fetch(
            self._pages_url(path),
            method=method,
            headers={"Accept": "application/json"},
            data=body or {},
        )
        self.last_response = resp
        return resp

    def _goto_list(self, handle: str | None = None):
        resp = self.page.goto(self._pages_url(handle=handle), wait_until="load")
        # The list is an Alpine component; it flags itself ready once rendered.
        self.page.wait_for_selector("#pages-app[data-ready='1']", timeout=5000)
        return resp

    def _row_titles(self) -> list[str]:
        return [
            el.inner_text().strip()
            for el in self.page.locator("#pages-list .page-title-link").all()
        ]

    def _row_slugs(self) -> list[str]:
        return [
            el.get_attribute("data-slug") or ""
            for el in self.page.locator("#pages-list .page-row").all()
        ]

    # ── actions ────────────────────────────────────────────────────────────────
    def _create_via_form(self, title: str, slug: str | None, content: str) -> None:
        self._goto_list()
        self.page.fill("#new-page-form input[name=title]", title)
        if slug is not None:
            self.page.fill("#new-page-form input[name=slug]", slug)
        self.page.fill("#new-page-form textarea[name=content]", _decode(content))
        self.page.click("#new-page-form button[type=submit]")
        self.page.wait_for_load_state("load")

    def create_page(self, title: str, content: str) -> None:
        self._create_via_form(title, None, content)

    def create_draft_page(self, title: str, slug: str, content: str) -> None:
        self._create_via_form(title, slug, content)

    def create_published_page(self, title: str, slug: str, visibility: str) -> None:
        self._create_via_form(title, slug, "")
        self._fetch("POST", f"/{slug}/visibility", {"visibility": visibility})

    def change_slug(self, slug: str, new_slug: str) -> None:
        self._fetch("PATCH", f"/{slug}", {"slug": new_slug})

    def update_content(self, slug: str, content: str) -> None:
        self._fetch("PATCH", f"/{slug}", {"content": _decode(content)})

    def delete_page(self, slug: str) -> None:
        self._fetch("DELETE", f"/{slug}")

    def publish_to_members(self, slug: str) -> None:
        self._fetch("POST", f"/{slug}/visibility", {"visibility": "members"})

    def publish_public(self, slug: str) -> None:
        self._fetch("POST", f"/{slug}/visibility", {"visibility": "public"})

    def try_publish_to_members(self, slug: str) -> None:
        self._fetch("POST", f"/{slug}/visibility", {"visibility": "members"})

    def owner_publish_to_members(self, slug: str) -> None:
        self._fetch("POST", f"/{slug}/visibility", {"visibility": "members"})

    def view_page(self, slug: str) -> None:
        self.last_response = self.page.goto(self._pages_url(f"/{slug}"), wait_until="load")

    def view_pages_list(self) -> None:
        self._goto_list()

    def visitor_open(self, slug: str, org_name: str) -> None:
        page = self.page_for(_VISITOR)
        self.last_response = page.goto(self._pages_url(f"/{slug}"), wait_until="load")

    def visitor_open_list(self, org_name: str) -> None:
        page = self.page_for(_VISITOR)
        self.last_response = page.goto(self._pages_url(), wait_until="load")

    # ── assertions ──────────────────────────────────────────────────────────--
    def assert_page_in_list(self, title: str) -> None:
        self._goto_list()
        titles = self._row_titles()
        assert title in titles, f"'{title}' not found in pages list: {titles}"

    def assert_page_absent(self, title: str) -> None:
        self._goto_list()
        titles = self._row_titles()
        assert title not in titles, f"'{title}' should be absent: {titles}"

    def assert_page_exists(self, slug: str) -> None:
        self._goto_list()
        assert slug in self._row_slugs(), f"page '{slug}' not found: {self._row_slugs()}"

    def assert_page_not_exists(self, slug: str) -> None:
        self._goto_list()
        assert slug not in self._row_slugs(), f"page '{slug}' should not exist"

    def assert_page_visibility(self, slug: str, visibility: str) -> None:
        self._goto_list()
        badge = self.page.locator(
            f"#pages-list .page-row[data-slug='{slug}'] .badge"
        ).get_attribute("data-visibility")
        assert badge == visibility, f"page '{slug}' visibility {badge!r}, expected {visibility!r}"

    def assert_view_contains(self, slug: str, text: str) -> None:
        self.page.goto(self._pages_url(f"/{slug}"), wait_until="load")
        assert text in self.page.content(), f"'{text}' not found in rendered page"

    def assert_rendered_heading(self, text: str) -> None:
        heading = self.page.locator("article h1").inner_text().strip()
        assert heading == text, f"heading is {heading!r}, expected {text!r}"

    def assert_rendered_list_item(self, text: str) -> None:
        items = [el.inner_text().strip() for el in self.page.locator("article li").all()]
        assert text in items, f"list item '{text}' not found in: {items}"

    def assert_rendered_shown(self) -> None:
        assert self.last_response is not None and self.last_response.status == 200, (
            f"expected 200, got {self.last_response.status if self.last_response else 'n/a'}"
        )

    def assert_cannot_edit(self, slug: str) -> None:
        self.page.goto(self._pages_url(f"/{slug}"), wait_until="load")
        assert self.page.locator("a.edit-link").count() == 0, "an edit link is shown"

    def assert_visible_to_members(self, slug: str) -> None:
        self.assert_page_visibility(slug, "members")

    def assert_visitor_can_view(self, slug: str, org_name: str) -> None:
        page = self.page_for(_VISITOR)
        resp = page.goto(self._pages_url(f"/{slug}"), wait_until="load")
        assert resp is not None and resp.status == 200, (
            f"visitor view got {resp.status if resp else 'n/a'}"
        )

    def assert_visitor_forbidden(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status in (403, 404), (
            f"expected 403/404, got {self.last_response.status}"
        )

    def assert_only_listed(self, title: str) -> None:
        titles = [
            el.inner_text().strip()
            for el in self.page_for(_VISITOR).locator("#pages-list .page-title-link").all()
        ]
        assert titles == [title], f"expected only [{title!r}], got {titles}"
