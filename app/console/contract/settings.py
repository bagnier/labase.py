"""Per-app settings — declared by apps, stored and served by the console.

The *write* counterpart to overviews: apps **declare** their settings (keys, types, defaults)
by answering :class:`ConsoleSettingsQuery`; the console persists overrides and serves the
effective value. Symmetric to the overview pull, but bidirectional.
"""

from dataclasses import dataclass, field
from typing import Literal

SettingType = Literal["string", "number", "boolean"]


@dataclass(frozen=True)
class SettingDef:
    key: str
    type: SettingType
    default: str  # stored as text, coerced by ``type``
    label: str


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
