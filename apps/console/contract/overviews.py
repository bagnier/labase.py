"""The console tiles, pulled from every app: like :mod:`apps.organizations.contract.overviews`
but server-wide, on the admin session, across all organizations.
"""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.vocabulary import AppName, PhosphorIcon

# The console landing sections, in display order.
SECTIONS: tuple[str, ...] = ("operations", "identity", "features", "configuration")


@dataclass(frozen=True)
class ConsoleOverview:
    key: AppName
    title: str
    icon: PhosphorIcon
    data: dict = field(default_factory=dict)  # JSON-serializable; "lines", "growth"
    group: str | None = None  # tiles sharing a group fold into one
    section: str = "features"  # one of SECTIONS
    href: str | None = None  # defaults to /console/{key}


@dataclass(frozen=True)
class ConsoleOverviewQuery:
    session: AsyncSession  # admin session
