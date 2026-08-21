import httpx

from tests.e2e.drivers.api_base import VISITOR, ApiBase


def _decode(content: str) -> str:
    """Gherkin passes ``\\n`` literally; turn it into a real newline for Markdown."""
    return content.replace("\\n", "\n")


class PagesApiMixin(ApiBase):
    def reset_session(self) -> None:
        self._pages_list: list[dict] | None = None
        self._viewed_page: dict | None = None
        self._public_page: dict | None = None
        super().reset_session()

    # ── helpers ────────────────────────────────────────────────────────────────
    def _handle(self) -> str:
        return getattr(self, "active_org_handle", "")

    def _pages_url(self, path: str = "", handle: str | None = None) -> str:
        return f"/{handle or self._handle()}/pages{path}"

    def _list(self, client: httpx.Client | None = None, handle: str | None = None) -> list[dict]:
        resp = (client or self.client()).get(self._pages_url(handle=handle))
        assert resp.status_code == 200, f"list pages got {resp.status_code}: {resp.text}"
        return resp.json()

    # ── actions ──────────────────────────────────────────────────────────────--
    def create_page(self, title: str, content: str) -> None:
        self.response = self.client().post(
            self._pages_url(), json={"title": title, "content": _decode(content)}
        )

    def open_new_page_form(self) -> None:
        self.response = self.client().get(self._pages_url("/new/edit"))
        assert self.response.status_code == 200, (
            f"new-page form GET got {self.response.status_code}: {self.response.text}"
        )

    def assert_pages_list_empty(self) -> None:
        pages = self._list()
        assert pages == [], f"expected an empty pages list, got: {[p['slug'] for p in pages]}"

    def create_draft_page(self, title: str, slug: str, content: str) -> None:
        self.response = self.client().post(
            self._pages_url(), json={"title": title, "slug": slug, "content": _decode(content)}
        )

    def create_published_page(self, title: str, slug: str, visibility: str) -> None:
        self.create_draft_page(title, slug, "")
        self._set_visibility(slug, visibility)

    def _set_visibility(self, slug: str, visibility: str) -> None:
        self.response = self.client().post(
            self._pages_url(f"/{slug}/visibility"), json={"visibility": visibility}
        )

    def change_slug(self, slug: str, new_slug: str) -> None:
        self.response = self.client().patch(self._pages_url(f"/{slug}"), json={"slug": new_slug})

    def update_content(self, slug: str, content: str) -> None:
        self.response = self.client().patch(
            self._pages_url(f"/{slug}"), json={"content": _decode(content)}
        )

    def delete_page(self, slug: str) -> None:
        self.response = self.client().delete(self._pages_url(f"/{slug}"))

    def publish_to_members(self, slug: str) -> None:
        self._set_visibility(slug, "members")

    def publish_public(self, slug: str) -> None:
        self._set_visibility(slug, "public")

    def try_publish_to_members(self, slug: str) -> None:
        self._set_visibility(slug, "members")

    def owner_publish_to_members(self, slug: str) -> None:
        self._set_visibility(slug, "members")

    def view_page(self, slug: str) -> None:
        self.response = self.client().get(self._pages_url(f"/{slug}"))
        self._viewed_page = self.response.json() if self.response.status_code == 200 else None

    def view_pages_list(self) -> None:
        self._pages_list = self._list()

    def visitor_open(self, slug: str, _org_name: str) -> None:
        self.response = self.client_for(VISITOR).get(self._pages_url(f"/{slug}"))

    def visitor_view_public_page(self, slug: str) -> None:
        self.response = self.client_for(VISITOR).get(f"/{slug}")
        self._public_page = self.response.json() if self.response.status_code == 200 else None

    def visitor_open_list(self, _org_name: str) -> None:
        self._pages_list = self._list(client=self.client_for(VISITOR))

    # ── assertions ───────────────────────────────────────────────────────────--
    def assert_page_in_list(self, title: str) -> None:
        titles = [p["title"] for p in self._list()]
        assert title in titles, f"'{title}' not found in pages list: {titles}"

    def assert_page_absent(self, title: str) -> None:
        titles = [p["title"] for p in self._list()]
        assert title not in titles, f"'{title}' should be absent: {titles}"

    # ── cross-tenant isolation ────────────────────────────────────────────────
    def view_pages_list_as(self, email: str) -> None:
        # The other tenant's org is seeded by the "is a member of" step; read its list from its
        # own handle.
        slug = getattr(self, "secondary_handles", {}).get(email, self._handle())
        self._viewed_page_titles = [
            p["title"] for p in self._list(client=self.client_for(email), handle=slug)
        ]

    def assert_page_hidden_from_view(self, title: str) -> None:
        titles = getattr(self, "_viewed_page_titles", None)
        assert titles is not None, "view the tenant's pages list first"
        assert title not in titles, f"'{title}' leaked into another tenant's pages list: {titles}"

    def assert_page_exists(self, slug: str) -> None:
        slugs = [p["slug"] for p in self._list()]
        assert slug in slugs, f"page '{slug}' not found: {slugs}"

    def assert_page_not_exists(self, slug: str) -> None:
        slugs = [p["slug"] for p in self._list()]
        assert slug not in slugs, f"page '{slug}' should not exist: {slugs}"

    def assert_page_visibility(self, slug: str, visibility: str) -> None:
        page = next((p for p in self._list() if p["slug"] == slug), None)
        assert page is not None, f"page '{slug}' not found"
        assert page["visibility"] == visibility, (
            f"page '{slug}' visibility is {page['visibility']!r}, expected {visibility!r}"
        )

    def _page(self, slug: str, client: httpx.Client | None = None) -> dict:
        """The page as its own document — the JSON face, not the markup the browser lane reads."""
        resp = (client or self.client()).get(self._pages_url(f"/{slug}"))
        assert resp.status_code == 200, f"view got {resp.status_code}: {resp.text}"
        return resp.json()

    def assert_view_contains(self, slug: str, text: str) -> None:
        content = self._page(slug)["content"]
        assert text in content, f"'{text}' not found in the page's content: {content!r}"

    def _opened_page(self) -> dict:
        page = getattr(self, "_viewed_page", None)
        assert page is not None, "open the page first"
        return page

    def assert_rendered_heading(self, text: str) -> None:
        # The heading *is* the title: the template renders it, the Markdown engine never sees it
        # (apps/pages/domain/render.py). The datum is what this lane can hold; the browser lane
        # holds the <h1> itself.
        title = self._opened_page()["title"]
        assert title == text, f"page title is {title!r}, expected {text!r}"

    def assert_rendered_list_item(self, text: str) -> None:
        body = self._opened_page()["body_html"]
        assert f"<li>{text}</li>" in body, f"list item '{text}' not in the rendered body: {body!r}"

    def assert_rendered_shown(self) -> None:
        body = self._opened_page()["body_html"]
        assert body, "the page came back with no rendered body"

    def assert_cannot_edit(self, slug: str) -> None:
        # The page says so itself, rather than the absence of a link in a template saying it for
        # it — and the neighbouring scenario holds the server side of the same rule.
        assert self._page(slug)["can_edit"] is False, f"page '{slug}' reports itself editable"

    def assert_visible_to_members(self, slug: str) -> None:
        assert self.response.status_code == 200, f"publish failed: {self.response.status_code}"
        self.assert_page_visibility(slug, "members")

    def assert_visitor_allowed(self) -> None:
        assert self.response.status_code == 200, (
            f"visitor view got {self.response.status_code}: {self.response.text}"
        )

    def assert_visitor_forbidden(self) -> None:
        assert self.response.status_code in (403, 404), (
            f"expected 403/404, got {self.response.status_code}"
        )

    def assert_only_listed(self, title: str) -> None:
        assert self._pages_list is not None, "call visitor_open_list first"
        titles = [p["title"] for p in self._pages_list]
        assert titles == [title], f"expected only [{title!r}], got {titles}"

    # ── nav helpers ────────────────────────────────────────────────────────────

    def _nav_url(self, path: str = "") -> str:
        return f"/{self._handle()}/pages/nav{path}"

    def _nav_candidates(self) -> list[dict]:
        resp = self.client().get(self._nav_url())
        assert resp.status_code == 200, f"nav GET got {resp.status_code}: {resp.text}"
        return resp.json()

    def _slug_for(self, title: str) -> str:
        candidates = self._nav_candidates()
        match = next((c for c in candidates if c["title"] == title), None)
        assert match is not None, f"no candidate with title {title!r}: {candidates}"
        return match["slug"]

    # ── nav actions ────────────────────────────────────────────────────────────

    def open_nav_manager(self) -> None:
        self.response = self.client().get(self._nav_url())

    def given_in_nav(self, title: str) -> None:
        slug = self._slug_for(title)
        resp = self.client().post(self._nav_url(), json={"slug": slug})
        assert resp.status_code == 201, f"add to nav got {resp.status_code}: {resp.text}"

    def add_to_nav(self, title: str) -> None:
        self.given_in_nav(title)

    def remove_from_nav(self, title: str) -> None:
        slug = self._slug_for(title)
        resp = self.client().delete(self._nav_url(f"/{slug}"))
        assert resp.status_code == 204, f"remove from nav got {resp.status_code}: {resp.text}"

    def move_nav_above(self, title: str, other: str) -> None:
        slug = self._slug_for(title)
        above_slug = self._slug_for(other)
        resp = self.client().put(
            self._nav_url(f"/{slug}/position"),
            json={"above_slug": above_slug},
        )
        assert resp.status_code == 200, f"reorder nav got {resp.status_code}: {resp.text}"

    # ── nav assertions ─────────────────────────────────────────────────────────

    def assert_in_nav(self, title: str) -> None:
        candidates = self._nav_candidates()
        match = next((c for c in candidates if c["title"] == title), None)
        assert match is not None, f"'{title}' not found: {candidates}"
        assert match["in_nav"], f"'{title}' not in nav: {candidates}"

    def assert_not_in_nav(self, title: str) -> None:
        candidates = self._nav_candidates()
        match = next((c for c in candidates if c["title"] == title), None)
        assert match is None or not match["in_nav"], f"'{title}' should not be in nav: {candidates}"

    def assert_nav_order(self, a: str, b: str) -> None:
        candidates = self._nav_candidates()
        in_nav = [c for c in candidates if c["in_nav"]]
        titles = [c["title"] for c in in_nav]
        assert titles.index(a) < titles.index(b), (
            f"expected '{a}' before '{b}', got order: {titles}"
        )

    def assert_not_nav_candidate(self, title: str) -> None:
        candidates = self._nav_candidates()
        titles = [c["title"] for c in candidates]
        assert title not in titles, f"'{title}' should not be a nav candidate: {titles}"

    def _public_nav_titles(self) -> list[str]:
        page = getattr(self, "_public_page", None)
        assert page is not None, "open the public page first"
        return [item["title"] for item in page["nav"]]

    def assert_page_nav_shows(self, title: str) -> None:
        titles = self._public_nav_titles()
        assert title in titles, f"nav link to '{title}' not offered: {titles}"

    def assert_page_nav_not_shows(self, title: str) -> None:
        titles = self._public_nav_titles()
        assert title not in titles, f"'{title}' should not be in the page nav: {titles}"
