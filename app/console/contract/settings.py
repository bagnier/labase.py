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
from typing import Literal

from app.console.domain.models import BOOL_FALSE, BOOL_TRUE, ENABLED_KEY
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


@dataclass(frozen=True)
class AppSettings:
    """An app's settings as read at mount time — carries the value of every declared setting.

    ``enabled`` is just one of them; the default only kicks in when the DB is unreachable
    (degraded mount, e.g. unit tests), since :func:`declare_app_settings` seeds the real row.
    """

    values: dict[str, str] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return self.values.get(ENABLED_KEY, BOOL_TRUE) != BOOL_FALSE


# Console-owned registry of declared metadata, filled at mount; the admin page reads it.
_declarations: dict[str, SettingsGroup] = {}


def declare_app_settings(
    app: str, defs: list[SettingDef], supabase: SupabaseLink | None = None
) -> None:
    """Declare ``app``'s settings: register their metadata and seed missing values in the DB."""
    _declarations[app] = SettingsGroup(app=app, defs=defs, supabase=supabase)
    seed_values(app, {d.key: d.default for d in defs})


def get_app_settings(app: str) -> AppSettings:
    """Read every persisted value for ``app`` (CRUD read)."""
    return AppSettings(read_values(app))


def declared_settings(app: str) -> SettingsGroup | None:
    """The metadata ``app`` declared at mount, or ``None`` if it declared none."""
    return _declarations.get(app)


def reset_declarations() -> None:
    """Clear the registry — for test isolation."""
    _declarations.clear()
