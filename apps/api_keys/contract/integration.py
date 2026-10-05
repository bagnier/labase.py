"""The api_keys mount: owner-only routes under ``/{org_handle}/api-keys``, a section of the org
settings page, and the answer to auth's ``ApiKeyQuery``. Deleting the app leaves auth untouched.
"""

from apps.api_keys.contract.events import ApiKeyIssued, ApiKeyRevoked
from apps.api_keys.domain.models import ApiKey, ApiKeyRead
from apps.api_keys.domain.service import hash_token
from apps.api_keys.infra.repository import ApiKeyRepository, resolve_key_principal
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
from apps.shared.integration.host import AppManifest, Host, MountPhase
from apps.shared.persistence.repository import count_where
from apps.shared.settings.live import SettingsDeclaration, SupabaseLink, feature_switch

PHASE = MountPhase.ORG


def mount(host: Host) -> None:
    host.register_app(
        AppManifest(
            settings=_declare_settings(),
            provides=[(ConsoleOverviewQuery, _console_overview)],
            routers=[(router, ORG_PREFIX)],
            emits=[ApiKeyIssued, ApiKeyRevoked],
            provides_when_enabled=[
                (OrgSettingsSectionQuery, _settings_section),
                (ApiKeyQuery, _resolve),
            ],
        )
    )


async def _settings_section(query: OrgSettingsSectionQuery) -> OrgSettingsSection:
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
    """The principal for a bearer token, limited to its org, or ``None`` for auth's 401. The
    request then runs under the creator's RLS claims."""
    if not query.token.startswith(API_KEY_PREFIX):
        return None
    principal = await resolve_key_principal(query.session, hash_token(query.token))
    if principal is None:
        return None
    created_by, org_id = principal
    email = (await resolve_user_emails([created_by])).get(created_by, "")
    return AuthenticatedUser(
        id=created_by,
        email=email,
        claims={"sub": str(created_by), "role": "authenticated", "email": email},
        api_key_org_id=org_id,
    )


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    total = await count_where(query.session, ApiKey)
    active = await count_where(query.session, ApiKey, ApiKey.revoked_at.is_(None))
    lines = [f"{active} active", f"{total - active} revoked"] if total else ["No API keys yet"]
    return ConsoleOverview(
        key="api_keys", title="API keys", icon="key", section="identity", data={"lines": lines}
    )
