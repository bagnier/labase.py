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
class SettingsGroup:
    app: str  # context id, e.g. "files"
    defs: list[SettingDef] = field(default_factory=list)


@dataclass(frozen=True)
class ConsoleSettingsQuery:
    """Asked by the console; each app answers with its :class:`SettingsGroup`."""
