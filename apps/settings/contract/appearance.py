"""App-wide appearance — a single console-managed DaisyUI theme applied to every page.

Unlike a per-browser preference, the theme is one server-side setting (``app_settings`` row)
that only console admins can change; it is rendered into ``<html data-theme>`` for all users.

The live value is exposed to every template via the ``app_theme()`` Jinja global (registered at
mount, next to ``css_v``), kept fresh by the ``SettingsChanged`` event like any other setting.
"""

from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import (
    AppSettings,
    SettingDef,
    SettingsChanged,
    declare_app_settings,
)
from apps.shared.host import Host

THEME_APP = "appearance"
THEME_KEY = "theme"
DEFAULT_THEME = "light"

# The themes enabled in static/css/input.css (@plugin "daisyui" { themes: ... }).
THEMES = [
    "light",
    "dark",
    "cupcake",
    "dracula",
    "emerald",
    "corporate",
    "synthwave",
    "retro",
    "nord",
    "business",
]

# Live handle: bound to its declared group at mount, refreshed by SettingsChanged.
appearance = AppSettings(THEME_APP)


def current_theme() -> str:
    """The active app-wide theme, falling back to the default for an unset/unknown value."""
    try:
        value = appearance.theme
    except AttributeError:
        return DEFAULT_THEME
    return value if value in THEMES else DEFAULT_THEME


async def _overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    return ConsoleOverview(
        key=THEME_APP,
        title="Appearance",
        icon="globe",
        data={"lines": [f"Theme: {current_theme()}"]},
    )


def mount(host: Host) -> None:
    """Declare the theme setting, wire the live handle, and register the console overview.

    The ``app_theme()`` / ``app_themes()`` Jinja globals are registered by the console mount
    (apps.settings.contract.integration) once templates are importable.
    """
    appearance.group = declare_app_settings(
        THEME_APP,
        defs=[
            SettingDef(
                THEME_KEY,
                "string",
                DEFAULT_THEME,
                "Application theme — applies to everyone (one of the enabled DaisyUI themes)",
            )
        ],
    )
    appearance.read()
    host.events.on(SettingsChanged, appearance.reload)
    host.events.on(ConsoleOverviewQuery, _overview)
