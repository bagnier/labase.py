"""App-wide appearance — a single console-managed DaisyUI theme applied to every page.

Unlike a per-browser preference, the theme is one server-side setting (``app_settings`` row)
that only console admins can change; it is rendered into ``<html data-theme>`` for all users.

The live value is exposed to every template via the ``app_theme()`` Jinja global (registered at
mount, next to ``asset``), kept fresh by the ``SettingsChanged`` event like any other setting.
"""

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.shared.settings.live import get_settings

THEME_APP = "appearance"
THEME_KEY = "theme"
DEFAULT_THEME = "labase-light"

# The themes available in ``static/css/input.css``, as an admin-selectable roster. The two
# ``labase-*`` names are custom themes declared with ``@plugin "daisyui/theme"`` — they carry the
# product identity and are the light/dark defaults; the rest are built-in daisyUI themes kept
# enabled in the ``@plugin "daisyui" { themes: ... }`` block. ``scripts/check_design_tokens.py``
# asserts this list stays in step with ``input.css``.
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
    """The active app-wide theme, falling back to the default for an unset/unknown value."""
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
