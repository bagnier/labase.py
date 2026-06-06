import os
from pathlib import Path

# Load .env.test values into the process environment, overriding any OS-level vars.
# pydantic-settings gives priority to env vars over .env files, so we force them here.
_env_test = Path(__file__).parent / ".env.test"
for _line in _env_test.read_text().splitlines():
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _, _v = _line.partition("=")
        os.environ[_k.strip()] = _v.strip()

from app.shared.config import get_settings  # noqa: E402
from app.shared.supabase_client import get_supabase, get_supabase_admin  # noqa: E402

get_settings.cache_clear()
get_supabase.cache_clear()
get_supabase_admin.cache_clear()

pytest_plugins = ["tests.bdd.steps"]
