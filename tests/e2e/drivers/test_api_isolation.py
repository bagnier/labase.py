"""The API driver's per-user clients, acting-user switch and ``reset_session``."""

import httpx
import pytest

from tests.e2e.drivers.api import ApiDriver
from tests.e2e.drivers.api_base import VISITOR

_JSON = {"accept": "application/json"}
_ALICE = "alice@example.com"
_BOB = "bob@example.com"


@pytest.fixture
def api(driver) -> ApiDriver:
    if not isinstance(driver, ApiDriver):
        pytest.skip("API-driver meta-test")
    return driver


def _whoami(client: httpx.Client) -> httpx.Response:
    return client.get("/profile", headers=_JSON)


def test_distinct_emails_get_isolated_sessions(api: ApiDriver) -> None:
    alice = api.client_for(_ALICE)
    bob = api.client_for(_BOB)

    assert alice is not bob
    assert _whoami(alice).json()["email"] == _ALICE
    assert _whoami(bob).json()["email"] == _BOB


def test_client_for_caches_one_instance_per_email(api: ApiDriver) -> None:
    first = api.client_for(_ALICE)
    second = api.client_for(_ALICE)
    assert first is second


def test_visitor_client_is_unauthenticated(api: ApiDriver) -> None:
    visitor = api.client_for(VISITOR)
    assert _whoami(visitor).status_code == 401


def test_client_follows_acting_email(api: ApiDriver) -> None:
    api.client_for(_ALICE)

    api.set_acting_email(_ALICE)
    assert api.client() is api.client_for(_ALICE)
    assert _whoami(api.client()).json()["email"] == _ALICE

    api.clear_acting_email()
    assert api.client() is api.client_for(VISITOR)


def test_set_acting_email_promotes_the_visitor_client(api: ApiDriver) -> None:
    visitor = api.client_for(VISITOR)

    api.set_acting_email(_ALICE)

    assert VISITOR not in api._clients
    assert api.client_for(_ALICE) is visitor
    assert api._acting_email == _ALICE


def test_sign_in_syncs_acting_email_with_the_authenticated_session(api: ApiDriver) -> None:
    email = "carol@example.com"
    api.ensure_registered(email, "Secret1!")
    api.sign_in(email, "Secret1!")

    assert api._acting_email == email
    assert VISITOR not in api._clients
    assert _whoami(api.client()).json()["email"] == email


def test_reset_session_closes_clients_and_resets_acting(api: ApiDriver) -> None:
    api.client_for(_ALICE)
    api.set_acting_email(_ALICE)

    api.reset_session()

    assert api._clients == {}
    assert api._acting_email == VISITOR
