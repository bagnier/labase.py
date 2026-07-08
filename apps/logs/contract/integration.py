"""How the logs context plugs into the running app.

``apps/logs`` is the single observability *read* context: it merges the firehose (a rotated
JSON file), the audit trail (``audit_logs``) and issue occurrences (``error_events``) into one
admin-only timeline, with an activity graph and structured export. The *write* primitives stay
in ``apps/shared/observability`` — a foundation every app imports downward.

NOTE: mounted BEFORE the console context so its /console/logs routes register ahead of the
console's /console/{app} catch-all.
"""

import structlog

from apps.logs.infra.router import router
from apps.shared.host import Host
from apps.shared.settings import SettingsDeclaration, SupabaseLink, feature_switch

log = structlog.get_logger("labase.logs")


def mount(host: Host) -> None:
    settings = host.register_settings(_declare_settings())
    if not settings.enabled:
        return
    host.app.include_router(router, prefix="/console/logs")


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="logs",
        defs=[feature_switch()],
        supabase=SupabaseLink("Browse the audit trail in Supabase", table="audit_logs"),
    )
