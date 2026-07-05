import pytest

from apps.settings.contract.settings import (
    AppSettings,
    SettingDef,
    SettingsChanged,
    SettingsGroup,
)
from apps.shared.bus import EventBus

_GROUP = SettingsGroup(
    "files",
    [
        SettingDef("max_upload_mb", "number", "25", "Max upload size"),
        SettingDef("uploads_enabled", "boolean", "true", "Allow uploads"),
    ],
)


def _settings() -> AppSettings:
    return AppSettings("files", raw={}, group=_GROUP)


@pytest.mark.asyncio
async def test_reload_and_coerce_to_declared_type() -> None:
    bus = EventBus()
    settings = _settings()
    bus.on(SettingsChanged, settings.reload)

    await bus.emit(SettingsChanged("files", {"max_upload_mb": "1", "uploads_enabled": "false"}))

    assert settings.max_upload_mb == 1  # int, not "1"
    assert settings.uploads_enabled is False  # bool, not "false"


@pytest.mark.asyncio
async def test_ignores_changes_for_other_apps() -> None:
    bus = EventBus()
    settings = _settings()
    bus.on(SettingsChanged, settings.reload)

    await bus.emit(SettingsChanged("todo", {"max_upload_mb": "1"}))

    assert settings.max_upload_mb == 25  # declared default, untouched


def test_unknown_setting_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        _ = _settings().nonexistent


_TYPED_GROUP = SettingsGroup(
    "demo",
    [
        SettingDef("title", "string", "Untitled", "A string"),
        SettingDef("limit", "number", "10", "A number"),
        SettingDef("active", "boolean", "true", "A boolean"),
    ],
)


def test_values_coerced_to_each_declared_type() -> None:
    settings = AppSettings(
        "demo",
        raw={"title": "Hello", "limit": "42", "active": "false"},
        group=_TYPED_GROUP,
    )

    assert settings.values == {"title": "Hello", "limit": 42, "active": False}


def test_missing_values_fall_back_to_declared_default_typed() -> None:
    settings = AppSettings("demo", raw={}, group=_TYPED_GROUP)

    # Defaults coerced too: "10" -> 10, "true" -> True, "Untitled" stays text.
    assert settings.values == {"title": "Untitled", "limit": 10, "active": True}


def test_non_numeric_number_passes_through_unchanged() -> None:
    settings = AppSettings("demo", raw={"limit": "lots"}, group=_TYPED_GROUP)

    assert settings.limit == "lots"


def test_undeclared_persisted_key_passes_through_as_text() -> None:
    settings = AppSettings("demo", raw={"stray": "5"}, group=_TYPED_GROUP)

    assert settings.stray == "5"  # no SettingDef -> left as the raw string


def test_no_group_leaves_everything_as_text() -> None:
    settings = AppSettings("demo", raw={"limit": "42"}, group=None)

    assert settings.limit == "42"


def test_merged_for_org_overlays_and_coerces():
    settings = _settings()
    values = settings.merged_for_org({"max_upload_mb": "5"})
    assert values["max_upload_mb"] == 5  # int, org override wins
    assert values["uploads_enabled"] is True  # untouched keys keep server defaults


def test_merged_for_org_without_override_keeps_server_values():
    settings = _settings()
    assert settings.merged_for_org({}) == settings.values
