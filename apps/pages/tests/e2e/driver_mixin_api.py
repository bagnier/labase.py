import httpx

from tests.e2e.drivers.api_base import VISITOR, ApiBase


def _decode(content: str) -> str:
    """Gherkin passes ``\\n`` literally; turn it into a real newline for Markdown."""
    return content.replace("\\n", "\n")


class PagesApiMixin(ApiBase):
    def reset_session(self) -> None:
        self.response: httpx.Response | None = None
        self._pages_list: list[dict] | None = None
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

    def view_pages_list(self) -> None:
        self._pages_list = self._list()

    def visitor_open(self, slug: str, org_name: str) -> None:
        self.response = self.client_for(VISITOR).get(self._pages_url(f"/{slug}"))

    def visitor_open_list(self, org_name: str) -> None:
        self._pages_list = self._list(client=self.client_for(VISITOR))

    # ── assertions ───────────────────────────────────────────────────────────--
    def assert_page_in_list(self, title: str) -> None:
        titles = [p["title"] for p in self._list()]
        assert title in titles, f"'{title}' not found in pages list: {titles}"

    def assert_page_absent(self, title: str) -> None:
        titles = [p["title"] for p in self._list()]
        assert title not in titles, f"'{title}' should be absent: {titles}"

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

    def assert_view_contains(self, slug: str, text: str) -> None:
        resp = self.client().get(self._pages_url(f"/{slug}"))
        assert resp.status_code == 200, f"view got {resp.status_code}: {resp.text}"
        assert text in resp.text, f"'{text}' not found in rendered page"

    def assert_rendered_heading(self, text: str) -> None:
        assert self.response is not None
        assert f"<h1>{text}</h1>" in self.response.text, (
            f"heading '{text}' not found in: {self.response.text}"
        )

    def assert_rendered_list_item(self, text: str) -> None:
        assert self.response is not None
        assert f"<li>{text}</li>" in self.response.text, (
            f"list item '{text}' not found in: {self.response.text}"
        )

    def assert_rendered_shown(self) -> None:
        assert self.response is not None
        assert self.response.status_code == 200, (
            f"expected 200, got {self.response.status_code}: {self.response.text}"
        )

    def assert_cannot_edit(self, slug: str) -> None:
        resp = self.client().get(self._pages_url(f"/{slug}"))
        assert resp.status_code == 200, f"view got {resp.status_code}"
        assert f"/pages/{slug}/edit" not in resp.text, "an edit link is shown but should not be"

    def assert_visible_to_members(self, slug: str) -> None:
        assert self.response is not None and self.response.status_code == 200, (
            f"publish failed: {self.response.status_code if self.response else 'n/a'}"
        )
        self.assert_page_visibility(slug, "members")

    def assert_visitor_can_view(self, slug: str, org_name: str) -> None:
        resp = self.client_for(VISITOR).get(self._pages_url(f"/{slug}"))
        assert resp.status_code == 200, f"visitor view got {resp.status_code}: {resp.text}"

    def assert_visitor_forbidden(self) -> None:
        assert self.response is not None
        assert self.response.status_code in (403, 404), (
            f"expected 403/404, got {self.response.status_code}"
        )

    def assert_only_listed(self, title: str) -> None:
        assert self._pages_list is not None, "call visitor_open_list first"
        titles = [p["title"] for p in self._pages_list]
        assert titles == [title], f"expected only [{title!r}], got {titles}"
