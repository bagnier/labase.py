"""Sections apps add to the owner-only org settings page, like dashboard cards: an app's owner
administration (API keys), neither a menu entry nor a metric.
"""

from dataclasses import dataclass, field

from apps.organizations.contract.collect import OrgMemberQuery
from apps.shared.vocabulary import AppName


@dataclass(frozen=True)
class OrgSettingsSection:
    key: AppName
    title: str
    template: str
    order: int = 50  # lower comes first
    data: dict = field(default_factory=dict)  # read by the partial


@dataclass(frozen=True)
class OrgSettingsSectionQuery(OrgMemberQuery):
    """Answered with an :class:`OrgSettingsSection`."""
