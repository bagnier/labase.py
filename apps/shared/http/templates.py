from pathlib import Path

from fastapi.templating import Jinja2Templates

_BASE = Path(__file__).parent.parent.parent
_CSS = _BASE.parent / "static" / "css" / "tailwind.css"

# No context processors: page context (incl. the shell — display name + nav orgs)
# is composed explicitly per route via apps.profile.contract.shell.
templates = Jinja2Templates(
    directory=[str(p) for p in sorted(_BASE.glob("*/templates")) if p.is_dir()],
)
templates.env.globals["css_v"] = int(_CSS.stat().st_mtime) if _CSS.exists() else 0
