from dotenv import load_dotenv

load_dotenv(".env.test", override=True)

from app.shared.config import get_settings  # noqa: E402
from app.shared.supabase_client import get_supabase, get_supabase_admin  # noqa: E402

get_settings.cache_clear()
get_supabase.cache_clear()
get_supabase_admin.cache_clear()

pytest_plugins = ["tests.bdd.steps"]
