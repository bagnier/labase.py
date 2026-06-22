"""Settings domain logic — framework-free. Merges declared defaults with persisted overrides
and validates a written value against its declared type."""

from app.console.contract.settings import SettingDef, SettingsGroup


class UnknownSetting(Exception):
    """A write targeted a key the app never declared."""


class InvalidSettingValue(Exception):
    """A written value does not match the setting's declared type."""


def effective_settings(group: SettingsGroup, overrides: dict[str, str]) -> list[dict]:
    """Each declared setting with its effective value (override if present, else default)."""
    return [
        {
            "key": d.key,
            "type": d.type,
            "label": d.label,
            "value": _normalise(d, overrides.get(d.key, d.default)),
        }
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
        if value not in ("true", "false"):
            raise InvalidSettingValue(f"{definition.key}={value!r} is not a boolean")
        return value
    return value
