from pathlib import Path
from typing import cast

from fastapi.templating import Jinja2Templates

_BASE = Path(__file__).parent.parent.parent
_CSS = _BASE.parent / "static" / "css" / "tailwind.css"

# No context processors: page context (incl. the fullpage slices — display name +
# nav orgs) is composed explicitly per route via apps.shared.page.
templates = Jinja2Templates(
    directory=[str(p) for p in sorted(_BASE.glob("*/templates")) if p.is_dir()],
)
_globals = cast("dict[str, object]", templates.env.globals)
_globals["css_v"] = int(_CSS.stat().st_mtime) if _CSS.exists() else 0
# Safe defaults; the console mount (apps.settings) overrides these with the live app-wide theme.
_globals["app_theme"] = lambda: "light"
_globals["app_themes"] = list
