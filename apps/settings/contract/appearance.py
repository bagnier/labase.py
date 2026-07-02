"""App-wide appearance — a single console-managed DaisyUI theme applied to every page.

Unlike a per-browser preference, the theme is one server-side setting (``app_settings`` row)
that only console admins can change; it is rendered into ``<html data-theme>`` for all users.

The live value is exposed to every template via the ``app_theme()`` Jinja global (registered at
mount, next to ``css_v``), kept fresh by the ``SettingsChanged`` event like any other setting.
"""

from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import AppSettings

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


async def overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    return ConsoleOverview(
        key=THEME_APP,
        title="Appearance",
        icon="globe",
        group="settings",
        data={"lines": [f"Theme: {current_theme()}"]},
    )
