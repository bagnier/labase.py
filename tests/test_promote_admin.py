"""What ``scripts/promote_admin.py`` says, beyond what it does.

The script is the documented way in — the Makefile names it as *the* way to become a server admin —
and it is run by someone who has just cloned the base, or who has locked themselves out. Both of
its silences cost a round trip:

- the claim lands in ``app_metadata``, which GoTrue embeds in the *access token*, so a session
  opened before the promotion carries none of it. "Promoted" with no admin button looks like a
  failure, and the fix is to sign in again;
- run from the host against a Docker-shaped ``.env``, it cannot resolve ``host.docker.internal``
  and dies in forty lines of httpx traceback that name neither the host nor the way round it.

Both are things the script knows and does not say, which is the only reason they are bugs.
"""

import os
from unittest.mock import patch

import httpx
import pytest

from scripts import promote_admin as pa


def test_promoting_rewrites_a_docker_only_env_file_to_the_host(tmp_path, monkeypatch):
    """Run from the host against a Docker-shaped ``.env``, the same rewrite `db-seed`,
    `preflight` and `backup-storage` apply — SUPABASE_API_URL reachable at 127.0.0.1 —
    instead of dying on `host.docker.internal`, which resolves only inside the app container."""
    env_file = tmp_path / ".env"
    env_file.write_text("SUPABASE_API_URL=http://host.docker.internal:54321\n")
    monkeypatch.setenv("ENV_FILE", str(env_file))
    monkeypatch.delenv("SUPABASE_API_URL", raising=False)

    with (
        patch.object(pa, "find_users", return_value=[type("U", (), {"id": "uid-1"})()]),
        patch.object(pa, "set_admin_role"),
    ):
        pa.promote_admin("az@az", None)

    assert os.environ["SUPABASE_API_URL"] == "http://127.0.0.1:54321"


def test_promoting_says_the_claim_only_lands_on_the_next_sign_in(capsys):
    with (
        patch.object(pa, "find_users", return_value=[type("U", (), {"id": "uid-1"})()]),
        patch.object(pa, "set_admin_role"),
    ):
        pa.promote_admin("az@az", None)

    assert "sign out and back in" in capsys.readouterr().out.lower()


def test_an_unreachable_gotrue_names_the_host_and_the_way_round_it(capsys):
    """The failure a Docker-shaped ``.env`` produces on the host, answered in one line instead of
    a traceback: the URL that was tried, and the override that reaches the same service."""
    with (
        patch.object(pa, "find_users", side_effect=httpx.ConnectError("nodename nor servname")),
        pytest.raises(SystemExit) as exit_code,
    ):
        pa.main_with_args("az@az", None)

    said = capsys.readouterr().err
    assert (exit_code.value.code, "SUPABASE_API_URL" in said) == (1, True)
