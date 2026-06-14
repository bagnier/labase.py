from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.profile.infra.context_processor import profile_context

_BASE = Path(__file__).parent.parent.parent

templates = Jinja2Templates(
    directory=[str(p) for p in sorted(_BASE.glob("*/templates")) if p.is_dir()],
    context_processors=[profile_context],
)
