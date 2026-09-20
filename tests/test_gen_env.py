"""`make env` gives the dev stack's `app_user` a password of its own, kept across refreshes."""

import re

from scripts.gen_env import build_overrides, user_password

_STATUS = {
    "API_URL": "http://127.0.0.1:54321",
    "DB_URL": "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
    "PUBLISHABLE_KEY": "pk",
    "SECRET_KEY": "sk",
}
_KEPT = "k" * 43


def test_a_refresh_keeps_the_password_the_env_file_holds(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        f"SUPABASE_DATABASE_USER_URL=postgresql+asyncpg://app_user:{_KEPT}@host:54322/postgres\n"
    )

    password = user_password(env)

    assert password == _KEPT


def test_a_weak_password_is_replaced_by_a_generated_one(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "SUPABASE_DATABASE_USER_URL="
        "postgresql+asyncpg://app_user:app_user_password@host:54322/postgres\n"
    )

    password = user_password(env)

    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", password) is not None


def test_a_missing_env_file_gets_a_generated_password(tmp_path):
    password = user_password(tmp_path / ".env")

    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", password) is not None


def test_the_user_url_carries_the_password():
    overrides = build_overrides(_STATUS, _KEPT)

    assert overrides["SUPABASE_DATABASE_USER_URL"] == (
        f"postgresql+asyncpg://app_user:{_KEPT}@host.docker.internal:54322/postgres"
    )


def test_a_stack_with_a_studio_gets_the_browser_facing_base():
    overrides = build_overrides({**_STATUS, "STUDIO_URL": "http://127.0.0.1:54323"}, _KEPT)

    assert overrides["SUPABASE_STUDIO_URL"] == "http://127.0.0.1:54323/project/default"


def test_a_stack_without_a_studio_leaves_the_key_empty():
    overrides = build_overrides(_STATUS, _KEPT)

    assert overrides["SUPABASE_STUDIO_URL"] == ""
