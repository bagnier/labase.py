import httpx

from tests.e2e.drivers.browser_base import BrowserBase


class ApiKeysBrowserMixin(BrowserBase):
    _api_key_secret: str | None = None
    _api_key_org_handle: str = ""

    def reset_session(self) -> None:
        self._api_key_secret = None
        self._api_key_org_handle = ""
        super().reset_session()

    def _open_keys_panel(self) -> None:
        """The keys section sits in the org settings page's "API keys" tab (client-side daisyUI
        tabs): in by the sidebar's owner-only Settings entry, then check the tab's radio."""
        self.follow_org_nav(getattr(self, "active_org_handle", ""), "settings")
        self.page.get_by_role("tab", name="API keys", exact=True).check()

    def create_api_key(self, name: str) -> None:
        self._open_keys_panel()
        self.page.get_by_label("Key name").fill(name)
        self.page.get_by_role("button", name="Create key").click()
        self.page.wait_for_selector("[data-api-key-secret]", timeout=5000)
        self._api_key_secret = self.page.locator("[data-api-key-secret]").inner_text().strip()
        self._api_key_org_handle = getattr(self, "active_org_handle", "")

    def assert_api_key_secret_revealed(self) -> None:
        assert self._api_key_secret is not None
        assert self._api_key_secret.startswith("lbk_"), self._api_key_secret
        # Reloading the page they are on is what "once" means: the secret is gone for good.
        self.page.reload(wait_until="load")
        assert self.page.locator("[data-api-key-secret]").count() == 0

    def _sessionless_get(self, path: str) -> httpx.Response:
        """Straight HTTP against the live server — no browser context, no cookies."""
        assert self._api_key_secret is not None, "no API key created"
        return httpx.get(
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self._api_key_secret}",
                "accept": "application/json",
            },
        )

    def assert_api_key_authenticates(self) -> None:
        resp = self._sessionless_get(f"/{self._api_key_org_handle}/todos")
        assert resp.status_code == 200, f"key rejected: {resp.status_code} {resp.text}"
        assert isinstance(resp.json(), list)

    def revoke_api_key(self, name: str) -> None:
        self._open_keys_panel()
        self.page.get_by_role("button", name=f"Revoke key {name}").click()
        self.page.wait_for_selector(
            f"[data-api-key='{name}'][data-api-key-status='revoked']", timeout=5000
        )

    def assert_api_key_rejected(self) -> None:
        resp = self._sessionless_get(f"/{self._api_key_org_handle}/todos")
        assert resp.status_code == 401, f"expected 401, got {resp.status_code}"

    def assert_api_key_rejected_on_active_org(self) -> None:
        other = getattr(self, "active_org_handle", "")
        assert other != self._api_key_org_handle, "scenario needs a different active org"
        resp = self._sessionless_get(f"/{other}/todos")
        assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"

    def try_open_api_keys_page(self) -> None:
        # The keys route is owner-gated; a member hitting it is blocked before any redirect.
        probe = getattr(self, "_probe_blocked", None)  # organizations mixin
        assert probe is not None
        slug = getattr(self, "active_org_handle", "")
        probe("GET", f"/{slug}/api-keys")
