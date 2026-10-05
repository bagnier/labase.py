"""What ``scripts/promote_admin.py`` tells its user: to sign in again (the token carries the
role), and, when GoTrue is unreachable, the URL tried rather than a traceback.
"""

import os
from unittest.mock import patch

import httpx
import pytest

from scripts import promote_admin as pa


def test_promoting_rewrites_a_docker_only_env_file_to_the_host(tmp_path, monkeypatch):
    """From the host, a Docker-shaped ``.env`` is rewritten to 127.0.0.1, like other scripts."""
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
    del os.environ["SUPABASE_API_URL"]  # set by apply_host_overrides, past monkeypatch


def test_promoting_says_the_claim_only_lands_on_the_next_sign_in(capsys):
    with (
        patch.object(pa, "find_users", return_value=[type("U", (), {"id": "uid-1"})()]),
        patch.object(pa, "set_admin_role"),
    ):
        pa.promote_admin("az@az", None)

    assert "sign out and back in" in capsys.readouterr().out.lower()


def test_an_unreachable_gotrue_names_the_host_and_the_way_round_it(capsys):
    """One line naming the URL tried and the override to use."""
    with (
        patch.object(pa, "find_users", side_effect=httpx.ConnectError("nodename nor servname")),
        pytest.raises(SystemExit) as exit_code,
    ):
        pa.main_with_args("az@az", None)

    said = capsys.readouterr().err
    assert (exit_code.value.code, "SUPABASE_API_URL" in said) == (1, True)
