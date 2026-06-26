import re

from tests.e2e.drivers.browser_base import _VISITOR, BrowserBase


def _decode(content: str) -> str:
    return content.replace("\\n", "\n")


def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "page"


class PagesBrowserMixin(BrowserBase):
    def _handle(self) -> str:
        return getattr(self, "active_org_handle", "")

    def _pages_url(self, path: str = "", handle: str | None = None) -> str:
        return f"{self.base_url}/{handle or self._handle()}/pages{path}"

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
        self.page.click('a[href$="/pages/new/edit"]')
        self.page.wait_for_selector("#edit-page-form", timeout=5000)
        self.page.fill("input[name=title]", title)
        self.page.fill("input[name=slug]", slug if slug is not None else _slugify(title))
        if content:
            self.page.fill(".cm-content", _decode(content))
        self._submit_edit_form()

    def create_page(self, title: str, content: str) -> None:
        self._create_via_form(title, None, content)

    def create_draft_page(self, title: str, slug: str, content: str) -> None:
        self._create_via_form(title, slug, content)

    def create_published_page(self, title: str, slug: str, visibility: str) -> None:
        self._create_via_form(title, slug, "")
        self._set_visibility_via_form(slug, visibility)

    def _goto_edit(self, slug: str) -> None:
        self._goto_list()
        self.page.click(f"#pages-list .page-row[data-slug='{slug}'] .page-edit-link")
        self.page.wait_for_load_state("load")

    def _submit_edit_form(self) -> None:
        with self.page.expect_navigation(wait_until="load"):
            self.page.click("#edit-page-form button[type=submit]")

    def change_slug(self, slug: str, new_slug: str) -> None:
        self._goto_edit(slug)
        self.page.fill("input[name=slug]", new_slug)
        self._submit_edit_form()

    def update_content(self, slug: str, content: str) -> None:
        self._goto_edit(slug)
        self.page.fill(".cm-content", _decode(content))
        self._submit_edit_form()

    def delete_page(self, slug: str) -> None:
        self._goto_edit(slug)
        self.page.on("dialog", lambda d: d.accept())
        with self.page.expect_navigation(wait_until="load"):
            self.page.click("#delete-page-btn")

    def _set_visibility_via_form(self, slug: str, visibility: str) -> None:
        self._goto_edit(slug)
        self.page.select_option("select[name=visibility]", visibility)
        self._submit_edit_form()

    def publish_to_members(self, slug: str) -> None:
        self._set_visibility_via_form(slug, "members")

    def publish_public(self, slug: str) -> None:
        self._set_visibility_via_form(slug, "public")

    def try_publish_to_members(self, slug: str) -> None:
        # The visibility control is hidden for members; probe the endpoint directly
        # to verify server-side enforcement (UI-hiding alone is not proof).
        self.last_response = self.page.request.fetch(
            self._pages_url(f"/{slug}/visibility"),
            method="POST",
            headers={"Accept": "application/json"},
            data={"visibility": "members"},
        )

    def owner_publish_to_members(self, slug: str) -> None:
        self._set_visibility_via_form(slug, "members")

    def view_page(self, slug: str) -> None:
        self._goto_list()
        self.page.click(f"#pages-list .page-row[data-slug='{slug}'] .page-title-link")
        self.page.wait_for_load_state("load")

    def view_pages_list(self) -> None:
        self._goto_list()

    def visitor_open(self, slug: str, _org_name: str) -> None:
        page = self.page_for(_VISITOR)
        self.last_response = page.goto(self._pages_url(f"/{slug}"), wait_until="load")

    def visitor_open_list(self, _org_name: str) -> None:
        page = self.page_for(_VISITOR)
        self.last_response = page.goto(self._pages_url(), wait_until="load")

    def visitor_view_public_page(self, slug: str) -> None:
        page = self.page_for(_VISITOR)
        self.last_response = page.goto(f"{self.base_url}/{slug}", wait_until="load")

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
        assert self.page.locator("article").count() > 0, "rendered page article not found"

    def assert_cannot_edit(self, slug: str) -> None:
        self.page.goto(self._pages_url(f"/{slug}"), wait_until="load")
        assert self.page.locator("a.edit-link").count() == 0, "an edit link is shown"

    def assert_visible_to_members(self, slug: str) -> None:
        self.assert_page_visibility(slug, "members")

    def assert_visitor_can_view(self, slug: str, _org_name: str) -> None:
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

    # ── nav helpers ────────────────────────────────────────────────────────────

    def _nav_url(self, path: str = "") -> str:
        return f"{self.base_url}/{self._handle()}/pages/nav{path}"

    def _goto_nav_manager(self) -> None:
        self.page.goto(self._nav_url(), wait_until="load")

    def _candidate_row(self, title: str):
        return self.page.locator("#nav-list .nav-candidate").filter(has_text=title)

    # ── nav actions ────────────────────────────────────────────────────────────

    def open_nav_manager(self) -> None:
        self._goto_list()
        self.page.click('a[href$="/pages/nav"]')
        self.page.wait_for_load_state("load")

    def given_in_nav(self, title: str) -> None:
        self._goto_nav_manager()
        row = self._candidate_row(title)
        cb = row.locator(".nav-checkbox")
        if not cb.is_checked():
            cb.click()
            self.page.wait_for_timeout(300)

    def add_to_nav(self, title: str) -> None:
        row = self._candidate_row(title)
        cb = row.locator(".nav-checkbox")
        if not cb.is_checked():
            cb.click()
            self.page.wait_for_timeout(300)

    def remove_from_nav(self, title: str) -> None:
        row = self._candidate_row(title)
        cb = row.locator(".nav-checkbox")
        if cb.is_checked():
            cb.click()
            self.page.wait_for_timeout(300)

    def move_nav_above(self, title: str, other: str) -> None:
        source = self._candidate_row(title).locator(".drag-handle")
        target = self._candidate_row(other).locator(".drag-handle")
        source.drag_to(target)
        self.page.wait_for_timeout(300)

    # ── nav assertions ─────────────────────────────────────────────────────────

    def assert_in_nav(self, title: str) -> None:
        self._goto_nav_manager()
        cb = self._candidate_row(title).locator(".nav-checkbox")
        assert cb.is_checked(), f"'{title}' checkbox is not checked"

    def assert_not_in_nav(self, title: str) -> None:
        self._goto_nav_manager()
        cb = self._candidate_row(title).locator(".nav-checkbox")
        assert not cb.is_checked(), f"'{title}' checkbox should not be checked"

    def assert_nav_order(self, a: str, b: str) -> None:
        self._goto_nav_manager()
        rows = self.page.locator("#nav-list .nav-candidate[data-in-nav='true']").all()
        titles = [r.inner_text().strip() for r in rows]
        a_idx = next((i for i, t in enumerate(titles) if a in t), None)
        b_idx = next((i for i, t in enumerate(titles) if b in t), None)
        assert a_idx is not None and b_idx is not None and a_idx < b_idx, (
            f"expected '{a}' before '{b}', got: {titles}"
        )

    def assert_not_nav_candidate(self, title: str) -> None:
        self._goto_nav_manager()
        rows = self.page.locator("#nav-list .nav-candidate").all()
        titles = [r.inner_text() for r in rows]
        assert not any(title in t for t in titles), (
            f"'{title}' should not appear as nav candidate: {titles}"
        )

    def assert_page_nav_shows(self, title: str) -> None:
        nav = self.page.locator('nav[aria-label="Page navigation"]')
        assert nav.count() > 0, "no page navigation found on page"
        links = [el.inner_text().strip() for el in nav.locator("a").all()]
        assert title in links, f"nav link to '{title}' not found: {links}"

    def assert_page_nav_not_shows(self, title: str) -> None:
        nav = self.page.locator('nav[aria-label="Page navigation"]')
        if nav.count() == 0:
            return
        links = [el.inner_text().strip() for el in nav.locator("a").all()]
        assert title not in links, f"'{title}' should not appear in page nav: {links}"
