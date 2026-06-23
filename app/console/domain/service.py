"""Settings domain logic — framework-free. Merges declared defaults with persisted overrides
and validates a written value against its declared type."""

from typing import TypedDict

from app.console.contract.settings import SettingDef, SettingsGroup, SettingType
from app.console.domain.models import BOOL_FALSE, BOOL_TRUE


class UnknownSetting(Exception):
    """A write targeted a key the app never declared."""


class InvalidSettingValue(Exception):
    """A written value does not match the setting's declared type."""


class EffectiveSetting(TypedDict):
    """A declared setting paired with its effective (override-or-default) value."""

    key: str
    type: SettingType
    label: str
    value: str


def coerce_bool(raw: object) -> bool:
    """Interpret an HTTP form/JSON value as a boolean (``True`` or the string ``"true"``)."""
    return raw is True or str(raw).lower() == BOOL_TRUE


def effective_settings(group: SettingsGroup, overrides: dict[str, str]) -> list[EffectiveSetting]:
    """Each declared setting with its effective value (override if present, else default)."""
    return [
        EffectiveSetting(
            key=d.key,
            type=d.type,
            label=d.label,
            value=_normalise(d, overrides.get(d.key, d.default)),
        )
        for d in group.defs
    ]


def validate(group: SettingsGroup, key: str, value: str) -> str:
    """Validate ``value`` against the declared :class:`SettingDef`; return its stored form."""
    definition = _find(group, key)
    return _normalise(definition, value)


def _find(group: SettingsGroup, key: str) -> SettingDef:
    for d in group.defs:
        if d.key == key:
            return d
    raise UnknownSetting(key)


def _normalise(definition: SettingDef, value: str) -> str:
    if definition.type == "number":
        try:
            return str(int(value))
        except ValueError:
            raise InvalidSettingValue(f"{definition.key}={value!r} is not a number") from None
    if definition.type == "boolean":
        if value not in (BOOL_TRUE, BOOL_FALSE):
            raise InvalidSettingValue(f"{definition.key}={value!r} is not a boolean")
        return value
    return value
