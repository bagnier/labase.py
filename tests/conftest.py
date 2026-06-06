from dotenv import load_dotenv

pytest_plugins = ["tests.bdd.steps"]


def pytest_configure(config):
    load_dotenv(".env.test", override=True)

    from app.shared.config import get_settings
    from app.shared.supabase_client import get_supabase, get_supabase_admin

    get_settings.cache_clear()
    get_supabase.cache_clear()
    get_supabase_admin.cache_clear()
