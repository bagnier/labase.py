"""The org dashboard cards (AGENTS: the dashboard collects one card per app). Each carries its
partial for the page and the same content as ``data`` for JSON: ``lines``, ``recent``.
"""

from dataclasses import dataclass, field

from apps.organizations.contract.collect import OrgQuery
from apps.shared.vocabulary import AppName, PhosphorIcon


@dataclass(frozen=True)
class Overview:
    key: AppName
    title: str
    icon: PhosphorIcon
    href: str  # relative to the org handle
    template: str
    data: dict = field(default_factory=dict)  # JSON-serializable; "lines", "recent"


@dataclass(frozen=True)
class OverviewQuery(OrgQuery):
    """Answered with an :class:`Overview`."""
