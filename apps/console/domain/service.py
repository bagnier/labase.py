"""Settings domain logic — framework-free. Pairs a declared setting with its stored value and
validates a written value against its declared type."""

from typing import TypedDict

from apps.shared.persistence.settings_store import BOOL_FALSE, BOOL_TRUE
from apps.shared.settings import SettingDef, SettingsDeclaration, SettingType


class UnknownSetting(Exception):
    """A write targeted a key the app never declared."""


class InvalidSettingValue(Exception):
    """A written value does not match the setting's declared type."""


class SettingView(TypedDict):
    """A declared setting paired with its stored value, for rendering the admin page."""

    key: str
    type: SettingType
    label: str
    value: str
    org_overridable: bool


def coerce_bool(raw: object) -> bool:
    """Interpret an HTTP form/JSON value as a boolean (``True`` or the string ``"true"``)."""
    return raw is True or str(raw).lower() == BOOL_TRUE


def settings_view(group: SettingsDeclaration, values: dict[str, str]) -> list[SettingView]:
    """Each declared setting paired with its stored value (declared default if not yet seeded)."""
    return [
        SettingView(
            key=d.key,
            type=d.type,
            label=d.label,
            value=_normalise(d, values.get(d.key, d.default)),
            org_overridable=d.org_overridable,
        )
        for d in group.defs
    ]


def validate(group: SettingsDeclaration, key: str, value: str) -> str:
    """Validate ``value`` against the declared :class:`SettingDef`; return its stored form."""
    definition = _find(group, key)
    return _normalise(definition, value)


def _find(group: SettingsDeclaration, key: str) -> SettingDef:
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
