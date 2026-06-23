"""Per-app settings — the console's settings service, used by every app from its ``mount()``.

The console is the repository and interface for settings. Each app, in ``mount()``:

1. **declares** the settings it needs (:func:`declare_app_settings`) — the single source that
   makes them editable in the console admin page *and* readable by the app;
2. **reads** their values (:func:`get_app_settings`) and wires itself — notably the ``enabled``
   gate, which is just a declared setting (via :func:`feature_switch`).

The DB stores *the value* of a setting (CRUD), nothing layered on top. A
:class:`SettingDef`'s ``default`` is merely the value seeded on first declaration. Setting
*metadata* (type, label, Supabase link) lives in memory — re-declared on every ``mount()``;
only the value is persisted.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from app.console.domain.models import BOOL_TRUE, ENABLED_KEY
from app.console.infra.store import read_values, seed_values

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
class SettingsGroup:
    """An app's declared settings: the in-memory metadata the console renders and validates."""

    app: str  # context id, e.g. "files"
    defs: list[SettingDef] = field(default_factory=list)
    supabase: SupabaseLink | None = None


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


# Console-owned registry of declared metadata, filled at mount; the admin page reads it.
_declarations: dict[str, SettingsGroup] = {}


def declare_app_settings(
    app: str, defs: list[SettingDef], supabase: SupabaseLink | None = None
) -> SettingsGroup:
    """Declare ``app``'s settings: register their metadata, seed missing values, return the
    group so a live :class:`AppSettings` can hold on to it."""
    group = SettingsGroup(app=app, defs=defs, supabase=supabase)
    _declarations[app] = group
    seed_values(app, {d.key: d.default for d in defs})
    return group


@dataclass(frozen=True)
class SettingsChanged:
    """A setting of ``app`` was edited in the console; carries the full fresh value set.

    A generic event: the console emits it knowing nothing of what the keys mean. Each app
    subscribes, filters on its own id, and reinterprets its own values.
    """

    app: str
    values: dict[str, str]


class AppSettings:
    """An app's settings: read a setting as an attribute — ``settings.max_upload_mb`` — and get
    its declared-typed value (``str``/``int``/``bool``); coercion is the console's job, so apps
    never do it.

    Holds a ref to its :class:`SettingsGroup` for the declared types. Construct cheaply (no I/O)
    as a module-level handle, bind the group at ``mount`` (``settings.group = declare_app_settings
    (...)``) and keep it live with ``host.events.on(SettingsChanged, settings.reload)``. Values
    are read from the DB lazily on first access, then refreshed by each event.
    """

    def __init__(
        self, app: str, raw: dict[str, str] | None = None, group: SettingsGroup | None = None
    ) -> None:
        self._app = app
        self._raw = raw  # None until first read; a dict once loaded or after a change
        self._group = group

    @property
    def group(self) -> SettingsGroup | None:
        # Bound explicitly at mount; falls back to the registry (and caches) for snapshots.
        if self._group is None:
            self._group = _declarations.get(self._app)
        return self._group

    @group.setter
    def group(self, group: SettingsGroup) -> None:
        self._group = group

    def read(self) -> None:
        """Read current values from the DB — call once at ``mount`` (sync, before the serving
        loop; :func:`read_values` drives :func:`asyncio.run`, which can't run inside it)."""
        self._raw = read_values(self._app)

    @property
    def values(self) -> dict[str, SettingValue]:
        group = self.group
        return _typed(group.defs if group is not None else [], self._raw or {})

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
        if event.app == self._app:
            self._raw = event.values


def get_app_settings(app: str) -> AppSettings:
    """A one-shot snapshot of ``app``'s persisted values (CRUD read), coerced to declared type."""
    return AppSettings(app, read_values(app))


def declared_settings(app: str) -> SettingsGroup | None:
    """The metadata ``app`` declared at mount, or ``None`` if it declared none."""
    return _declarations.get(app)


def reset_declarations() -> None:
    """Clear the registry — for test isolation."""
    _declarations.clear()
