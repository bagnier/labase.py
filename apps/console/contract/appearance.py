"""The app-wide daisyUI theme, one server setting rendered as ``<html data-theme>`` for every
user, read by templates through the ``app_theme()`` global.
"""

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.shared.settings.live import get_settings

THEME_APP = "appearance"
THEME_KEY = "theme"
DEFAULT_THEME = "labase-light"

# The themes ``static/css/input.css`` enables: the two custom ``labase-*`` (light and dark
# defaults), then built-in daisyUI ones. ``scripts/check_design_tokens.py`` keeps them in step.
THEMES = [
    "labase-light",
    "labase-dark",
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


def current_theme() -> str:
    """The active theme; the default for an unknown value."""
    try:
        value = get_settings(THEME_APP).theme
    except KeyError, AttributeError:
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
