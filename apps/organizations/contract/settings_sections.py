"""Org settings sections — the settings page's *pull* collaboration surface.

Org-scoped apps contribute one :class:`OrgSettingsSection` each to the org settings page by
answering the :class:`OrgSettingsSectionQuery` (``host.contribs.provide(
OrgSettingsSectionQuery, provider)`` at mount). The settings page gathers them at runtime
with ``contribs.collect(OrgSettingsSectionQuery(...))`` — a failing provider is isolated, not
fatal. Providers stay ignorant of one another and of the settings page.

Each section carries its own Jinja partial (``template``, embedded on the settings page via
``{% include %}``) plus the ``data`` that partial reads. This mirrors the dashboard's
:class:`~apps.organizations.contract.overviews.Overview` seam, scoped to the owner-only
settings page instead of the dashboard.

This is the home for owner-scoped administration of an app (e.g. managing API keys): it is
*not* a menu destination, so it earns no sidebar ``NavItem``; and it is *not* an at-a-glance
metric, so it is *not* a dashboard ``Overview``. It is a setting of the org — hence here.
"""

from dataclasses import dataclass, field

from apps.organizations.contract.collect import OrgMemberQuery


@dataclass(frozen=True)
class OrgSettingsSection:
    key: str  # context id, e.g. "api_keys"
    title: str  # human title, e.g. "API keys"
    template: str  # the app's own Jinja partial, embedded on the settings page
    order: int = 50  # display order; lower comes first
    data: dict = field(default_factory=dict)  # vars the partial reads


@dataclass(frozen=True)
class OrgSettingsSectionQuery(OrgMemberQuery):
    """Asked by the org settings page; each app answers with its
    :class:`OrgSettingsSection` (one collect grammar — see
    :mod:`apps.organizations.contract.collect`)."""
