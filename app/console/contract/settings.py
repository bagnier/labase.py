"""Per-app settings — declared by apps, stored and served by the console.

The *write* counterpart to overviews: apps **declare** their settings (keys, types, defaults)
by answering :class:`ConsoleSettingsQuery`; the console persists overrides and serves the
effective value. Symmetric to the overview pull, but bidirectional.
"""

from dataclasses import dataclass, field
from typing import Literal

from app.console.domain.models import BOOL_FALSE, BOOL_TRUE, ENABLED_KEY
from app.console.infra.startup import load_app_overrides

SettingType = Literal["string", "number", "boolean"]

# A toggleable app declares the reserved on/off switch (:data:`ENABLED_KEY`) like any other
# setting (via :func:`feature_switch`); the difference is purely in the read —
# :func:`get_app_settings` consults it before mounting, so a change applies on the next restart.


@dataclass(frozen=True)
class SettingDef:
    key: str
    type: SettingType
    default: str  # stored as text, coerced by ``type``
    label: str


def feature_switch(label: str = "Enabled (applies on restart)") -> SettingDef:
    """The reserved on/off switch a toggleable app adds to its :class:`SettingsGroup`."""
    return SettingDef(ENABLED_KEY, "boolean", "true", label)


@dataclass(frozen=True)
class AppSettings:
    """An app's persisted overrides, read once at mount time (:mod:`app.console.infra.startup`).

    ``values`` holds every stored key→value override for the app; ``enabled`` is the decision
    derived from the reserved :data:`ENABLED_KEY`, surfaced as a field so a toggleable app
    can gate its ``mount`` without re-deriving the on/off rule.
    """

    app: str
    values: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


def get_app_settings(app_id: str) -> AppSettings:
    """Read ``app_id``'s persisted settings at mount time — the contract entry point.

    The DB read lives in :mod:`app.console.infra.startup`; here it is wrapped into the decision
    on the reserved :data:`ENABLED_KEY`.
    """
    values = load_app_overrides(app_id)
    return AppSettings(
        app=app_id, values=values, enabled=values.get(ENABLED_KEY, BOOL_TRUE) != BOOL_FALSE
    )


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
    app: str  # context id, e.g. "files"
    defs: list[SettingDef] = field(default_factory=list)
    supabase: SupabaseLink | None = None


@dataclass(frozen=True)
class ConsoleSettingsQuery:
    """Asked by the console; each app answers with its :class:`SettingsGroup`."""
