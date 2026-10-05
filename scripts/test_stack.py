"""The checkout's own Supabase stack for tests: users and mail belong to a stack, not a schema.
Its name and ports come from `.env.test`, so `supabase/` is used as is.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from apps.shared.settings.env import TechnicalSettings, get_technical_settings
from scripts.provision_schema import db_port

# Unused by the suite: the stack keeps db, auth, rest, storage, mailpit.
_EXCLUDED = "studio,imgproxy,edge-runtime,logflare,vector,realtime"


def project_id(checkout: str) -> str:
    return f"labase-{checkout.replace('.', '-')}-test"


def cli_ports(settings: TechnicalSettings) -> dict[str, str]:
    db_url = settings.supabase_database_admin_url or settings.supabase_database_user_url
    return {
        "SUPABASE_API_PORT": str(urlsplit(settings.supabase_api_url).port),
        "SUPABASE_DB_PORT": str(db_port(db_url)),
        "SUPABASE_LOCAL_SMTP_PORT": str(urlsplit(settings.mailpit_url).port),
        "SUPABASE_LOCAL_SMTP_SMTP_PORT": str(settings.smtp_port),
    }


def prunable_worktrees(porcelain: str) -> list[str]:
    """Worktrees git lists whose directory is gone."""
    return [
        Path(lines[0].removeprefix("worktree ")).name
        for lines in (record.splitlines() for record in porcelain.split("\n\n"))
        if any(line.split(" ", 1)[0] == "prunable" for line in lines)
    ]


def _cli_env(checkout: str) -> dict[str, str]:
    return {
        **os.environ,
        "SUPABASE_PROJECT_ID": project_id(checkout),
        **cli_ports(get_technical_settings()),
    }


def start(checkout: str) -> None:
    env = _cli_env(checkout)
    subprocess.run(["supabase", "start", "-x", _EXCLUDED], env=env, check=True)
    subprocess.run(["supabase", "migration", "up", "--local"], env=env, check=True)
    print(f"{project_id(checkout)} up")


def stop(checkout: str) -> None:
    """Remove the stack and its volumes, then those of worktrees git lists as prunable."""
    subprocess.run(["supabase", "stop", "--no-backup"], env=_cli_env(checkout), check=True)
    listing = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout
    for name in prunable_worktrees(listing):
        orphan = {**os.environ, "SUPABASE_PROJECT_ID": project_id(name)}
        subprocess.run(["supabase", "stop", "--no-backup"], env=orphan, check=True)
        print(f"{project_id(name)} removed — its worktree directory is gone")


def main() -> int:
    if sys.argv[1:] not in (["start"], ["stop"]):
        print("usage: scripts/test_stack.py start|stop", file=sys.stderr)
        return 2
    (start if sys.argv[1] == "start" else stop)(Path.cwd().name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
