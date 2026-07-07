"""Per-app settings — cross-cutting, like :mod:`apps.shared.bus`/``email``/``queue``: every app
declares its settings from its own ``mount()``, so the mechanism lives here rather than in a
bounded context ``Host`` couldn't reach.

Each app, in ``mount()``, declares the settings it needs via ``host.register_settings(...)`` —
the single call that makes them editable in the console admin page (:mod:`apps.console`), seeds
their defaults, and brings the app's live :class:`AppSettings` handle current. The ``enabled``
gate a toggleable app checks right after is just a declared setting (via :func:`feature_switch`),
read straight off that same handle.

The DB stores *the value* of a setting (CRUD), nothing layered on top. A :class:`SettingDef`'s
``default`` is merely the value seeded on first declaration. Setting *metadata* (type, label,
Supabase link) lives in memory — re-declared on every ``mount()``; only the value is persisted.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.persistence.settings_store import (
    BOOL_TRUE,
    ENABLED_KEY,
    OrgAppSetting,
    read_values,
    seed_values,
)

SettingType = Literal["string", "number", "boolean"]


@dataclass(frozen=True)
class SettingDef:
    key: str
    type: SettingType
    default: str  # the value seeded on first declaration; stored as text, coerced by ``type``
    label: str


def feature_switch(label: str = "Enabled (applies on restart)") -> SettingDef:
    """The reserved on/off switch a toggleable app declares — an ordinary boolean setting."""
    return SettingDef(ENABLED_KEY, "boolean", "true", label)


@dataclass(frozen=True)
class SupabaseLink:
    """A deep link into Supabase Studio for advanced, out-of-console management.

    The console prefixes the derived Studio base URL onto either:
    - ``path`` — a static Studio-relative fragment (e.g. ``auth/users``,
      ``storage/buckets/org-files``); or
    - ``table`` — a Postgres table name; the console resolves its OID at request time and
      points the Studio *table editor* straight at it (Studio has no name-based route).
    """

    label: str
    path: str = ""
    table: str | None = None


@dataclass(frozen=True)
class ConsoleLink:
    """A console screen an app contributes beyond its settings page (e.g. ``/console/accounts``).

    Declared at mount like everything else, so the console overview and the app's
    settings page link to it — and deleting the app removes the link.
    """

    label: str
    href: str


@dataclass(frozen=True)
class SettingsDeclaration:
    """What an app declares at mount: the in-memory metadata the console renders and validates,
    bundled so :meth:`Host.register_settings` takes one payload instead of a growing kwarg list."""

    app_name: str  # context id, e.g. "files"
    defs: list[SettingDef] = field(default_factory=list)
    supabase: SupabaseLink | None = None
    links: tuple[ConsoleLink, ...] = ()


SettingValue = str | int | bool


def _coerce(kind: SettingType, raw: str) -> SettingValue:
    if kind == "number":
        try:
            return int(raw)
        except ValueError:
            return raw
    if kind == "boolean":
        return raw == BOOL_TRUE
    return raw


def _typed(defs: list[SettingDef], values: dict[str, str]) -> dict[str, SettingValue]:
    """``values`` coerced to the type each :class:`SettingDef` declares — the console's job, so
    the apps reading them never have to.

    Every declared setting is present, falling back to its declared default when not yet
    persisted; extra persisted keys (no declaration) pass through as text.
    """
    typed: dict[str, SettingValue] = {
        d.key: _coerce(d.type, values.get(d.key, d.default)) for d in defs
    }
    for key, raw in values.items():
        typed.setdefault(key, raw)
    return typed


@dataclass(frozen=True)
class SettingsChanged:
    """A setting of ``app`` was edited in the console; carries the full fresh value set.

    A generic event: the console emits it knowing nothing of what the keys mean. Each app
    subscribes, filters on its own id, and reinterprets its own values.
    """

    app_name: str
    values: dict[str, str]


class AppSettings:
    """An app's settings: read a setting as an attribute — ``settings.max_upload_mb`` — and get
    its declared-typed value (``str``/``int``/``bool``); coercion is the console's job, so apps
    never do it.

    Holds a ref to its :class:`SettingsDeclaration` for the declared types. Construct cheaply
    (no I/O) as a module-level handle; ``host.register_settings(settings, ...)`` binds
    ``declaration``, seeds values, does the initial read, and subscribes it to
    ``SettingsChanged`` — all in one call from ``mount()``. Values are read from the DB lazily
    on first access, then refreshed by each event.
    """

    def __init__(
        self,
        raw: dict[str, str] | None = None,
        declaration: SettingsDeclaration | None = None,
    ) -> None:
        self._raw = raw  # None until first read; a dict once loaded or after a change
        self.declaration = declaration  # bound explicitly by Host.register_settings

    def read(self) -> None:
        """Read current values from the DB — call once at ``mount``, after ``declaration`` is
        bound (sync, before the serving loop; :func:`read_values` drives :func:`asyncio.run`,
        which can't run inside it)."""
        assert self.declaration is not None, "read() requires declaration to be bound first"
        self._raw = read_values(self.declaration.app_name)

    @property
    def values(self) -> dict[str, SettingValue]:
        declaration = self.declaration
        return _typed(declaration.defs if declaration is not None else [], self._raw or {})

    def __getattr__(self, name: str) -> Any:
        # A setting's static type depends on its key, so it's ``Any`` here; the value is coerced
        # to its declared ``str``/``int``/``bool`` at runtime. Only reached for setting keys.
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self.values[name]
        except KeyError:
            raise AttributeError(name) from None

    async def reload(self, event: SettingsChanged) -> None:
        """Console event handler: adopt the fresh values when they're for this app."""
        if self.declaration is not None and event.app_name == self.declaration.app_name:
            self._raw = event.values

    def merged_for_org(self, overrides: dict[str, str]) -> dict[str, SettingValue]:
        """Server-wide values overlaid with per-org overrides, coerced to declared types."""
        declaration = self.declaration
        defs = declaration.defs if declaration is not None else []
        return _typed(defs, {**(self._raw or {}), **overrides})

    async def for_org(self, session: AsyncSession, org_id: uuid.UUID) -> dict[str, SettingValue]:
        """This org's effective settings — the server value unless the console overrode it.

        Read fresh per call through the caller's session: the RLS policy lets org
        members read their own org's overrides, so the regular request session works
        and no cache needs invalidating across instances.
        """
        assert self.declaration is not None, "for_org() requires declaration to be bound first"
        return self.merged_for_org(await org_values(session, self.declaration.app_name, org_id))


async def org_values(session: AsyncSession, app_name: str, org_id: uuid.UUID) -> dict[str, str]:
    """Raw per-org overrides of `app` for `org_id` (RLS: members see their own org)."""
    rows = await session.execute(
        select(OrgAppSetting.key, OrgAppSetting.value).where(
            OrgAppSetting.app_name == app_name, OrgAppSetting.org_id == org_id
        )
    )
    return {key: value for key, value in rows.all()}


def bind_settings(settings: AppSettings, declaration: SettingsDeclaration) -> None:
    """Seed missing values, bind ``settings.declaration``, and read its current persisted
    values — everything :meth:`Host.register_settings` does that doesn't touch ``host`` itself
    (registering into ``host.declarations``, subscribing to ``host.events``)."""
    seed_values(declaration.app_name, {d.key: d.default for d in declaration.defs})
    settings.declaration = declaration
    settings.read()
