from pathlib import Path
from typing import cast

from fastapi.templating import Jinja2Templates

_BASE = Path(__file__).parent.parent.parent
_STATIC_DIR = _BASE.parent / "static"


def asset(path: str) -> str:
    """A ``/static/…`` URL stamped with the file's mtime (``?v=…``) so the browser refetches
    it the moment the content changes — which is exactly what lets ``CachingStaticFiles`` serve
    it ``immutable``. Missing files degrade to the bare path. Cheap enough to stat per render."""
    file = _STATIC_DIR / path.removeprefix("/static/")
    return f"{path}?v={int(file.stat().st_mtime)}" if file.is_file() else path


# No context processors: page context (incl. the fullpage slices — display name +
# nav orgs) is composed explicitly per route via apps.shared.page.
templates = Jinja2Templates(
    directory=[str(p) for p in sorted(_BASE.glob("*/templates")) if p.is_dir()],
)
_globals = cast("dict[str, object]", templates.env.globals)
_globals["asset"] = asset
# Safe defaults; the console mount (apps.console) overrides these with the live app-wide theme,
# and the timeline mount (apps.timeline) with the log levels it actually accepts — an option list
# belongs to the app that owns the setting, not to the console page that renders it.
_globals["app_theme"] = lambda: "light"
_globals["app_themes"] = list
_globals["log_levels"] = list
