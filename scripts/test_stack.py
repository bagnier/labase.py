"""The checkout's own local Supabase stack for tests, beside the dev stack `make dev` uses.

`auth.users` and the mail catcher belong to a stack, not to a schema, so a test run can only
leave another checkout's users and `make dev` data alone by running on a stack of its own. The
CLI takes the stack's identity from `SUPABASE_PROJECT_ID` and its ports from `SUPABASE_*_PORT`,
read from the env file the suite itself reads (`.env.test`), so `supabase/` is used as is.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from apps.shared.settings.env import TechnicalSettings, get_technical_settings
from scripts.provision_schema import db_port

# Services the suite never touches (avatars are raw Storage downloads, no edge functions, no
# realtime channels, Studio is for humans): the stack keeps db, auth, rest, storage, mailpit.
_EXCLUDED = "studio,imgproxy,edge-runtime,logflare,vector,realtime"


def project_id(checkout: str) -> str:
    return f"labase-{checkout.replace('.', '-')}-test"


def cli_ports(settings: TechnicalSettings) -> dict[str, str]:
    """The four ports a stack without Studio, analytics and realtime binds on the host."""
    db_url = settings.supabase_database_admin_url or settings.supabase_database_user_url
    return {
        "SUPABASE_API_PORT": str(urlsplit(settings.supabase_api_url).port),
        "SUPABASE_DB_PORT": str(db_port(db_url)),
        "SUPABASE_LOCAL_SMTP_PORT": str(urlsplit(settings.mailpit_url).port),
        "SUPABASE_LOCAL_SMTP_SMTP_PORT": str(settings.smtp_port),
    }


def prunable_worktrees(porcelain: str) -> list[str]:
    """Names of the worktrees git still lists but whose directory is gone, from
    `git worktree list --porcelain` — a record per worktree, `worktree <path>` first."""
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
    """Idempotent: a running stack answers `supabase start` in a second."""
    env = _cli_env(checkout)
    subprocess.run(["supabase", "start", "-x", _EXCLUDED], env=env, check=True)
    subprocess.run(["supabase", "migration", "up", "--local"], env=env, check=True)
    print(f"{project_id(checkout)} up")


def stop(checkout: str) -> None:
    """Removes the stack with its volumes — the next start is a fresh database — then the stacks
    of worktrees deleted without `make worktree-rm`, which git still lists as prunable. A
    `git worktree remove` leaves no such trace, so its stack is not found here."""
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
