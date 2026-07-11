"""How the api_keys context plugs into the running app.

Single composition entry (:func:`mount`): mounts the owner-only management router under
/{org_handle}/api-keys (create/revoke + JSON list), contributes the keys panel as a section
of the org settings page (answering ``OrgSettingsSectionQuery``), and answers auth's
``ApiKeyQuery`` — the seam that turns an ``Authorization: Bearer lbk_...`` header into an
authenticated, org-pinned principal. Deleting this context removes the feature without
touching auth.
"""

from sqlalchemy import func, select

from apps.api_keys.domain.models import ApiKey, ApiKeyRead
from apps.api_keys.domain.service import hash_token
from apps.api_keys.infra.repository import ApiKeyRepository, resolve_active_key, touch_last_used
from apps.api_keys.infra.router import router
from apps.auth.contract.admin import resolve_user_emails
from apps.auth.contract.api_keys import API_KEY_PREFIX, ApiKeyQuery
from apps.auth.contract.user import AuthenticatedUser
from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.settings_sections import (
    OrgSettingsSection,
    OrgSettingsSectionQuery,
)
from apps.shared.host import AppManifest, Host, MountPhase
from apps.shared.settings import SettingsDeclaration, SupabaseLink, feature_switch

PHASE = MountPhase.ORG


def mount(host: Host) -> None:
    host.register_app(
        AppManifest(
            settings=_declare_settings(),
            on=[(ConsoleOverviewQuery, _console_overview)],
            routers=[(router, ORG_PREFIX)],
            when_enabled=[(OrgSettingsSectionQuery, _settings_section), (ApiKeyQuery, _resolve)],
        )
    )


async def _settings_section(query: OrgSettingsSectionQuery) -> OrgSettingsSection:
    """Answer the org settings page: the org's API keys, as an embedded management section."""
    repo = ApiKeyRepository(query.session, query.org_id)
    keys = [ApiKeyRead.model_validate(k) for k in await repo.all()]
    return OrgSettingsSection(
        key="api_keys",
        title="API keys",
        template="api_keys/_settings_section.html",
        data={"keys": keys},
    )


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="api_keys",
        defs=[feature_switch()],
        supabase=SupabaseLink("Browse API keys in Supabase", table="api_keys"),
    )


async def _resolve(query: ApiKeyQuery) -> AuthenticatedUser | None:
    """Bearer token → org-pinned principal; None lets auth answer 401.

    Runs pre-auth on the request's admin session (no JWT exists yet — the hash
    lookup is the explicit check). RLS still applies downstream: the request
    proceeds with the key creator's synthesized claims.
    """
    if not query.token.startswith(API_KEY_PREFIX):
        return None
    key = await resolve_active_key(query.session, hash_token(query.token))
    if key is None:
        return None
    await touch_last_used(query.session, key)
    created_by, org_id = key.created_by, key.org_id
    email = (await resolve_user_emails([created_by])).get(created_by, "")
    return AuthenticatedUser(
        id=str(created_by),
        email=email,
        claims={"sub": str(created_by), "role": "authenticated", "email": email},
        api_key_org_id=org_id,
    )


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    total = await query.session.scalar(select(func.count()).select_from(ApiKey)) or 0
    active = (
        await query.session.scalar(
            select(func.count()).select_from(ApiKey).where(ApiKey.revoked_at.is_(None))
        )
        or 0
    )
    lines = [f"{active} active", f"{total - active} revoked"] if total else ["No API keys yet"]
    return ConsoleOverview(
        key="api_keys", title="API keys", icon="key", section="configuration", data={"lines": lines}
    )
