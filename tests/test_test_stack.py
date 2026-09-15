"""The checkout's own test stack: its name, and the ports the CLI binds it on.

Pure mapping only — starting a stack is the Makefile's `test-stack` target, exercised by the
suite itself running against it.
"""

from apps.shared.settings.env import TechnicalSettings
from scripts import test_stack


def test_project_id_names_the_checkout():
    assert test_stack.project_id("labase.py") == "labase-labase-py-test"


def test_cli_ports_are_the_ones_the_test_settings_point_at():
    # A block no env file uses, so the values can only come from this object.
    settings = TechnicalSettings(
        supabase_api_url="http://127.0.0.1:55521",
        supabase_publishable_key="sb_publishable_x",
        supabase_secret_key="sb_secret_x",
        supabase_database_user_url="postgresql+asyncpg://postgres:postgres@127.0.0.1:55522/postgres",
        supabase_database_admin_url="postgresql+asyncpg://postgres:postgres@127.0.0.1:55522/postgres",
        mailpit_url="http://127.0.0.1:55524",
        smtp_port=55525,
    )

    ports = test_stack.cli_ports(settings)

    assert ports == {
        "SUPABASE_API_PORT": "55521",
        "SUPABASE_DB_PORT": "55522",
        "SUPABASE_LOCAL_SMTP_PORT": "55524",
        "SUPABASE_LOCAL_SMTP_SMTP_PORT": "55525",
    }
