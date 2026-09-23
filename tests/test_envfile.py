"""A host-side script (`make db-seed`, `make preflight`, `make backup-storage`) reads the same
`.env` `docker compose` writes for the app container, whose `host.docker.internal` host only
resolves inside Docker (see README's `.env` vs `.env.test`) — it needs the same service reached
at `127.0.0.1` instead.
"""

import os

from scripts.envfile import apply_host_overrides, host_reachable_overrides


def test_a_host_reachable_env_file_needs_no_override(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SUPABASE_API_URL=http://127.0.0.1:54321\n")

    assert host_reachable_overrides(env) == {}


def test_a_docker_only_url_is_rewritten_to_the_host(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SUPABASE_API_URL=http://host.docker.internal:54321\n")

    assert host_reachable_overrides(env) == {"SUPABASE_API_URL": "http://127.0.0.1:54321"}


def test_every_docker_only_setting_is_rewritten(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "SUPABASE_API_URL=http://host.docker.internal:54321\n"
        "SUPABASE_STORAGE_URL=http://host.docker.internal:54321\n"
        "SUPABASE_DATABASE_USER_URL="
        "postgresql+asyncpg://app_user:pw@host.docker.internal:54322/postgres\n"
        "SUPABASE_DATABASE_ADMIN_URL="
        "postgresql+asyncpg://postgres:postgres@host.docker.internal:54322/postgres\n"
        "SMTP_HOST=host.docker.internal\n"
    )

    assert host_reachable_overrides(env) == {
        "SUPABASE_API_URL": "http://127.0.0.1:54321",
        "SUPABASE_STORAGE_URL": "http://127.0.0.1:54321",
        "SUPABASE_DATABASE_USER_URL": "postgresql+asyncpg://app_user:pw@127.0.0.1:54322/postgres",
        "SUPABASE_DATABASE_ADMIN_URL": (
            "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
        ),
        "SMTP_HOST": "127.0.0.1",
    }


def test_a_setting_outside_the_tracked_list_is_left_untouched(tmp_path):
    env = tmp_path / ".env"
    env.write_text("MAILPIT_URL=http://host.docker.internal:54324\n")

    assert host_reachable_overrides(env) == {}


def test_a_missing_env_file_needs_no_override(tmp_path):
    assert host_reachable_overrides(tmp_path / ".env") == {}


def test_a_rewritten_value_is_applied_when_nothing_is_set_yet(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SUPABASE_API_URL=http://host.docker.internal:54321\n")
    monkeypatch.delenv("SUPABASE_API_URL", raising=False)

    apply_host_overrides(env)

    assert os.environ["SUPABASE_API_URL"] == "http://127.0.0.1:54321"


def test_a_value_already_set_is_left_alone(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SUPABASE_API_URL=http://host.docker.internal:54321\n")
    monkeypatch.setenv("SUPABASE_API_URL", "http://example.com")

    apply_host_overrides(env)

    assert os.environ["SUPABASE_API_URL"] == "http://example.com"
