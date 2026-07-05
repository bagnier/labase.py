import httpx

from tests.e2e.drivers.api_base import ApiBase


class ApiKeysApiMixin(ApiBase):
    _api_key_secret: str | None = None
    _api_key_org_handle: str = ""

    def reset_session(self) -> None:
        self._api_key_secret = None
        self._api_key_org_handle = ""
        super().reset_session()

    def _keys_url(self, handle: str | None = None) -> str:
        slug = handle if handle is not None else getattr(self, "active_org_handle", "")
        return f"/{slug}/api-keys"

    def create_api_key(self, name: str) -> None:
        resp = self.client().post(self._keys_url(), json={"name": name})
        assert resp.status_code == 201, f"create key: {resp.status_code} {resp.text}"
        self._api_key_secret = resp.json()["secret"]
        self._api_key_org_handle = getattr(self, "active_org_handle", "")

    def assert_api_key_secret_revealed(self) -> None:
        assert self._api_key_secret is not None
        assert self._api_key_secret.startswith("lbk_"), self._api_key_secret
        keys = self.client().get(self._keys_url()).json()
        assert all("secret" not in k for k in keys), "the secret must never be listed again"

    def _sessionless_get(self, path: str) -> httpx.Response:
        """A fresh client with no cookie jar — only the Authorization header speaks."""
        assert self._api_key_secret is not None, "no API key created"
        client = self._make_client()
        try:
            return client.get(path, headers={"Authorization": f"Bearer {self._api_key_secret}"})
        finally:
            client.close()

    def assert_api_key_authenticates(self) -> None:
        resp = self._sessionless_get(f"/{self._api_key_org_handle}/todos")
        assert resp.status_code == 200, f"key rejected: {resp.status_code} {resp.text}"
        assert isinstance(resp.json(), list)

    def revoke_api_key(self, name: str) -> None:
        keys = self.client().get(self._keys_url()).json()
        key = next((k for k in keys if k["name"] == name), None)
        assert key is not None, f"no key named {name!r}: {keys}"
        resp = self.client().delete(f"{self._keys_url()}/{key['id']}")
        assert resp.status_code == 204, f"revoke: {resp.status_code} {resp.text}"

    def assert_api_key_rejected(self) -> None:
        resp = self._sessionless_get(f"/{self._api_key_org_handle}/todos")
        assert resp.status_code == 401, f"expected 401, got {resp.status_code}"

    def assert_api_key_rejected_on_active_org(self) -> None:
        other = getattr(self, "active_org_handle", "")
        assert other != self._api_key_org_handle, "scenario needs a different active org"
        resp = self._sessionless_get(f"/{other}/todos")
        assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"

    def try_open_api_keys_page(self) -> None:
        self.response = self.client().get(self._keys_url())
