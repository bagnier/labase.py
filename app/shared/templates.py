from pathlib import Path

from fastapi.templating import Jinja2Templates

_BASE = Path(__file__).parent.parent

templates = Jinja2Templates(directory=[
    str(_BASE / "shared" / "templates"),
    str(_BASE / "auth" / "templates"),
    str(_BASE / "profile" / "templates"),
])
