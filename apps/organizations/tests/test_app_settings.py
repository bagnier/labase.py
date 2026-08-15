"""The ``app_settings`` dependency resolves *the request's effective settings*:
org overrides only under ``/{org_handle}`` with an authenticated caller, server values
everywhere else."""

import uuid
from types import SimpleNamespace

import pytest

import apps.shared.settings as shared_settings
from apps.organizations.contract import current
from apps.organizations.contract.current import app_settings
from apps.shared.settings import AppSettings, SettingDef, SettingsDeclaration

_DECLARATION = SettingsDeclaration("demo", [SettingDef("limit", "number", "10", "A number")])


@pytest.fixture
def demo_settings(monkeypatch) -> AppSettings:
    handle = AppSettings(raw={}, declaration=_DECLARATION)
    monkeypatch.setitem(shared_settings._registry, "demo", handle)
    return handle


@pytest.mark.asyncio
async def test_route_without_org_resolves_server_values(demo_settings):
    resolve = app_settings("demo")
    view = await resolve(SimpleNamespace(path_params={}), object(), None)
    assert view.limit == 10


@pytest.mark.asyncio
async def test_anonymous_request_resolves_server_values(demo_settings):
    resolve = app_settings("demo")
    view = await resolve(SimpleNamespace(path_params={"org_handle": "acme"}), None, None)
    assert view.limit == 10


@pytest.mark.asyncio
async def test_org_route_overlays_that_orgs_overrides(demo_settings, monkeypatch):
    org_id = uuid.uuid7()

    async def fake_current_org(request, user, session):
        return org_id

    async def fake_org_values(session, app_name, resolved_org):
        assert (app_name, resolved_org) == ("demo", org_id)
        return {"limit": "3"}

    monkeypatch.setattr(current, "get_current_org", fake_current_org)
    monkeypatch.setattr(shared_settings, "org_values", fake_org_values)

    resolve = app_settings("demo")
    view = await resolve(SimpleNamespace(path_params={"org_handle": "acme"}), object(), None)
    assert view.limit == 3
