"""The Jinja environment, built from every app's ``templates/`` directory.

No context processor: a page's context is explicit, per route (AGENTS: a page's context is
assembled from slices its apps own). Globals hold only what no route could supply.
"""

from pathlib import Path
from typing import cast

from fastapi.templating import Jinja2Templates

_BASE = Path(__file__).parent.parent.parent
_STATIC_DIR = _BASE.parent / "static"


def asset(path: str) -> str:
    """``path`` with its mtime as ``?v=…``, so it can be served ``immutable``; the bare path if
    the file is missing."""
    file = _STATIC_DIR / path.removeprefix("/static/")
    return f"{path}?v={int(file.stat().st_mtime)}" if file.is_file() else path


templates = Jinja2Templates(
    directory=[str(p) for p in sorted(_BASE.glob("*/templates")) if p.is_dir()],
)
_globals = cast("dict[str, object]", templates.env.globals)
_globals["asset"] = asset
# Defaults; apps.console sets the live theme, apps.timeline the log levels it accepts.
_globals["app_theme"] = lambda: "light"
_globals["app_themes"] = list
_globals["log_levels"] = list
