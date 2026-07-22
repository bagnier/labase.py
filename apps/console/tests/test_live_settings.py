import pytest

import apps.shared.settings as shared_settings
from apps.shared.settings import (
    AppSettings,
    SettingDef,
    SettingsChanged,
    SettingsDeclaration,
    get_settings,
)

_DECLARATION = SettingsDeclaration(
    "files",
    [
        SettingDef("max_upload_mb", "number", "25", "Max upload size"),
        SettingDef("uploads_enabled", "boolean", "true", "Allow uploads"),
    ],
)


def _settings() -> AppSettings:
    return AppSettings(raw={}, declaration=_DECLARATION)


@pytest.mark.asyncio
async def test_reload_and_coerce_to_declared_type() -> None:
    settings = _settings()
    # ``settings.reload`` is the ``spread`` handler the tailer replays off the trail; applying it
    # adopts the fresh values, coerced to their declared types on the next read.
    await settings.reload(
        SettingsChanged(app_name="files", values={"max_upload_mb": "1", "uploads_enabled": "false"})
    )

    assert settings.max_upload_mb == 1  # int, not "1"
    assert settings.uploads_enabled is False  # bool, not "false"


@pytest.mark.asyncio
async def test_ignores_changes_for_other_apps() -> None:
    settings = _settings()

    await settings.reload(SettingsChanged(app_name="todo", values={"max_upload_mb": "1"}))

    assert settings.max_upload_mb == 25  # declared default, untouched


def test_unknown_setting_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        _ = _settings().nonexistent


_TYPED_DECLARATION = SettingsDeclaration(
    "demo",
    [
        SettingDef("title", "string", "Untitled", "A string"),
        SettingDef("limit", "number", "10", "A number"),
        SettingDef("active", "boolean", "true", "A boolean"),
    ],
)


def test_values_coerced_to_each_declared_type() -> None:
    settings = AppSettings(
        raw={"title": "Hello", "limit": "42", "active": "false"},
        declaration=_TYPED_DECLARATION,
    )

    assert settings.values == {"title": "Hello", "limit": 42, "active": False}


def test_missing_values_fall_back_to_declared_default_typed() -> None:
    settings = AppSettings(raw={}, declaration=_TYPED_DECLARATION)

    # Defaults coerced too: "10" -> 10, "true" -> True, "Untitled" stays text.
    assert settings.values == {"title": "Untitled", "limit": 10, "active": True}


def test_non_numeric_number_passes_through_unchanged() -> None:
    settings = AppSettings(raw={"limit": "lots"}, declaration=_TYPED_DECLARATION)

    assert settings.limit == "lots"


def test_undeclared_persisted_key_passes_through_as_text() -> None:
    settings = AppSettings(raw={"stray": "5"}, declaration=_TYPED_DECLARATION)

    assert settings.stray == "5"  # no SettingDef -> left as the raw string


def test_no_declaration_leaves_everything_as_text() -> None:
    settings = AppSettings(raw={"limit": "42"}, declaration=None)

    assert settings.limit == "42"


def test_merged_for_org_overlays_and_coerces():
    settings = _settings()
    values = settings.merged_for_org({"max_upload_mb": "5"})
    assert values.max_upload_mb == 5  # int, org override wins
    assert values.uploads_enabled is True  # untouched keys keep server defaults


def test_merged_for_org_without_override_keeps_server_values():
    settings = _settings()
    assert settings.merged_for_org({}).values == settings.values


def test_coercion_is_cached_and_dropped_on_write():
    settings = _settings()
    first = settings.values
    assert settings.values is first  # same dict: not re-coerced on every attribute access
    settings._raw = {"max_upload_mb": "7"}  # any write path drops the cache
    assert settings.max_upload_mb == 7


def test_view_exposes_server_values_read_only():
    view = _settings().view()
    assert view.max_upload_mb == 25
    assert view.uploads_enabled is True


def test_get_settings_returns_the_registered_handle(monkeypatch):
    handle = _settings()
    monkeypatch.setitem(shared_settings._registry, "demo-app", handle)
    assert get_settings("demo-app") is handle


def test_get_settings_unknown_app_raises_key_error():
    with pytest.raises(KeyError):
        get_settings("never-mounted")
