"""Live settings: each app declares its own at mount with ``host.register_settings(...)``, which
makes them editable in the console, seeds their defaults and registers the app's
:class:`AppSettings` handle. The database stores only values; types and labels are re-declared on
every mount.

A contract never exports a handle (AGENTS: a contract never exports a settings handle). Three
reads, chosen by how the org is known:

- from the URL, ``/{org_handle}``: the ``app_settings(name)`` dependency
  (:mod:`apps.organizations.contract.current`);
- from data (a share-link download's file row): ``get_settings(name).for_org(session, org_id)``;
- no org (server-wide values, mount, tasks, event handlers): ``get_settings(name)``.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events import BusinessEvent
from apps.shared.settings.store import (
    BOOL_TRUE,
    ENABLED_KEY,
    OrgAppSetting,
    read_values,
    seed_values,
)
from apps.shared.vocabulary import AppName, PhosphorIcon

SettingType = Literal["string", "number", "boolean"]


class SettingRow(TypedDict):
    """A declared setting and its stored value as display strings, for the console templates."""

    key: str
    type: SettingType
    label: str
    value: str


@dataclass(frozen=True)
class SettingDef:
    """One declared setting. ``default`` is text, seeded on first declaration.

    ``org_overridable=False`` for a server-only setting (the promoted org handle): no per-org
    override in the console, and the override endpoint rejects it.
    """

    key: str
    type: SettingType
    default: str
    label: str
    org_overridable: bool = True


def feature_switch(label: str = "Enabled (applies on restart)") -> SettingDef:
    """The on/off switch of a toggleable app. Applied on restart, so never per org."""
    return SettingDef(ENABLED_KEY, "boolean", "true", label, org_overridable=False)


@dataclass(frozen=True)
class SupabaseLink:
    """A link into Supabase Studio, shown only when ``SUPABASE_STUDIO_URL`` is set.

    Either ``path``, relative to Studio (``auth/users``), or ``table``, whose OID the console
    resolves at request time: Studio's table editor has no route by name.
    """

    label: str
    path: str = ""
    table: str | None = None


@dataclass(frozen=True)
class ConsoleLink:
    """A console screen an app adds beyond its settings page (``/console/accounts``)."""

    label: str
    href: str


@dataclass(frozen=True)
class SettingsDeclaration:
    """What an app passes to :meth:`Host.register_settings`."""

    app_name: AppName
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
    """``values`` coerced to their declared types, defaults filling the gaps. Undeclared keys
    stay text."""
    typed: dict[str, SettingValue] = {
        d.key: _coerce(d.type, values.get(d.key, d.default)) for d in defs
    }
    for key, raw in values.items():
        typed.setdefault(key, raw)
    return typed


def _lookup(values: dict[str, SettingValue], name: str) -> Any:
    if name.startswith("_"):
        raise AttributeError(name)
    try:
        return values[name]
    except KeyError:
        raise AttributeError(name) from None


class SettingsView:
    """Read-only merged values, read as attributes like :class:`AppSettings`."""

    __slots__ = ("values",)

    def __init__(self, values: dict[str, SettingValue]) -> None:
        self.values = values

    def __getattr__(self, name: str) -> Any:
        return _lookup(self.values, name)


@dataclass(frozen=True, kw_only=True)
class SettingsChanged(BusinessEvent):
    """A server-wide setting of ``target_app`` was edited in the console.

    Both the record of who changed what and the propagation: it carries every fresh value, and
    each instance's :meth:`AppSettings.reload` (a ``spread`` handler) adopts them.
    """

    verb: ClassVar[str] = "server_changed"
    app_name: ClassVar[AppName] = "settings"
    icon: ClassVar[PhosphorIcon] = "gear"

    # ``app_name`` owns the kind ("settings"); this names the app whose setting changed.
    target_app: AppName
    key: str
    value: str
    values: dict[str, str] = field(default_factory=dict)


class AppSettings:
    """An app's server-wide settings, read as typed attributes: ``settings.max_upload_mb``.

    Live handles come from ``host.register_settings``. Tests may construct one directly; an empty
    ``raw`` answers every read with the declared defaults.
    """

    def __init__(self, raw: dict[str, str], declaration: SettingsDeclaration) -> None:
        self._raw_values = raw
        self._declaration = declaration
        self._typed: dict[str, SettingValue] | None = None  # None: recoerce on next read

    @property
    def declaration(self) -> SettingsDeclaration:
        return self._declaration

    @declaration.setter
    def declaration(self, declaration: SettingsDeclaration) -> None:
        self._declaration = declaration
        self._typed = None

    @property
    def _defs(self) -> list[SettingDef]:
        return self._declaration.defs

    @property
    def _raw(self) -> dict[str, str]:
        return self._raw_values

    @_raw.setter
    def _raw(self, raw: dict[str, str]) -> None:
        # Every write goes through here, so the cache never outlives a change.
        self._raw_values = raw
        self._typed = None

    def read(self) -> None:
        """Load the stored values. Sync: call at mount, before the event loop runs."""
        self._raw = read_values(self._declaration.app_name)

    def snapshot(self) -> dict[str, str]:
        """See :func:`settings_snapshot`."""
        return dict(self._raw)

    def restore(self, raw: dict[str, str]) -> None:
        """See :func:`settings_snapshot`."""
        self._raw = raw

    @property
    def values(self) -> dict[str, SettingValue]:
        if self._typed is None:
            self._typed = _typed(self._defs, self._raw)
        return self._typed

    def view(self) -> SettingsView:
        """The server-wide values, as a request outside any org gets them."""
        return SettingsView(self.values)

    def rows(self) -> list[SettingRow]:
        """Every declared setting with its stored text, which ``validate`` normalised on write."""
        raw = self._raw
        return [
            SettingRow(key=d.key, type=d.type, label=d.label, value=str(raw.get(d.key, d.default)))
            for d in self._defs
        ]

    def __getattr__(self, name: str) -> Any:
        """Typed ``Any``: the type depends on the key."""
        return _lookup(self.values, name)

    async def reload(self, event: SettingsChanged) -> None:
        """``spread`` handler: adopt the fresh values if they are this app's."""
        if event.target_app == self._declaration.app_name:
            self._raw = event.values

    def merged_for_org(self, overrides: dict[str, str]) -> SettingsView:
        return SettingsView(_typed(self._defs, {**self._raw, **overrides}))

    async def for_org(self, session: AsyncSession, org_id: uuid.UUID) -> SettingsView:
        """This org's effective values, read on each call: RLS lets members read their org's
        overrides, and no cache needs invalidating across instances."""
        return self.merged_for_org(await org_values(session, self.declaration.app_name, org_id))


async def org_values(session: AsyncSession, app_name: str, org_id: uuid.UUID) -> dict[str, str]:
    """The org's stored overrides of ``app_name``."""
    rows = await session.execute(
        select(OrgAppSetting.key, OrgAppSetting.value).where(
            OrgAppSetting.app_name == app_name, OrgAppSetting.org_id == org_id
        )
    )
    return {key: value for key, value in rows.all()}


# One handle per app, reused when tests mount a fresh ``Host``, so ``get_settings`` stays stable.
_registry: dict[str, AppSettings] = {}


def get_settings(app_name: str) -> AppSettings:
    """A mounted app's handle. Its attributes are server-wide values, sync and I/O-free; per-org
    values are async (see the module docstring)."""
    try:
        return _registry[app_name]
    except KeyError:
        raise KeyError(f"no settings registered for app '{app_name}' — is it mounted?") from None


def settings_snapshot() -> dict[str, dict[str, str]]:
    """Every handle's values, copied.

    A test rolling back a console edit undoes the row, not the in-memory handles; restoring this
    snapshot undoes the rest.
    """
    return {name: handle.snapshot() for name, handle in _registry.items()}


def restore_settings(snapshot: dict[str, dict[str, str]]) -> None:
    """Re-point every handle at a :func:`settings_snapshot`."""
    for name, raw in snapshot.items():
        handle = _registry.get(name)
        if handle is not None:
            handle.restore(raw)


def bind_settings(declaration: SettingsDeclaration) -> AppSettings:
    """Seed missing values, bind ``declaration`` to the app's handle and load its values: the
    part of :meth:`Host.register_settings` that does not touch the host."""
    seed_values(declaration.app_name, {d.key: d.default for d in declaration.defs})
    settings = _registry.setdefault(declaration.app_name, AppSettings({}, declaration))
    settings.declaration = declaration
    settings.read()
    return settings
