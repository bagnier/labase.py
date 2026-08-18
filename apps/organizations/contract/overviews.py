"""Dashboard compositions — org's *pull* collaboration surface, carried by the contribs registry.

Org-scoped apps contribute one :class:`Overview` each to the org dashboard by answering the
:class:`OverviewQuery` (``host.contribs.provide(OverviewQuery, provider)`` at mount). The org
dashboard gathers them at runtime with ``contribs.collect(OverviewQuery(...))`` — a failing
provider is isolated, not fatal. Providers stay ignorant of one another and of the dashboard.

Each overview carries both a *web view* (the app's own Jinja partial, rendered on the
dashboard) and *structured data* (a JSON-serializable dict, exposed via the REST endpoint).
By convention ``data`` holds ``lines`` (short metric strings) and ``recent`` (recent item
labels); both surfaces render the same content.
"""

from dataclasses import dataclass, field

from apps.organizations.contract.collect import OrgQuery
from apps.shared.vocabulary import AppName, PhosphorIcon


@dataclass(frozen=True)
class Overview:
    key: AppName
    title: str
    icon: PhosphorIcon
    href: str  # link into the app, relative to the org handle
    template: str  # the app's own Jinja partial (web view)
    data: dict = field(default_factory=dict)  # JSON-serializable; "lines"/"recent"


@dataclass(frozen=True)
class OverviewQuery(OrgQuery):
    """Asked by the org dashboard; each app answers with its :class:`Overview`
    (one collect grammar — see :mod:`apps.organizations.contract.collect`)."""
