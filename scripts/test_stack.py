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
    """Removes the stack with its volumes: the next start is a fresh database."""
    subprocess.run(["supabase", "stop", "--no-backup"], env=_cli_env(checkout), check=True)


def main() -> int:
    if sys.argv[1:] not in (["start"], ["stop"]):
        print("usage: scripts/test_stack.py start|stop", file=sys.stderr)
        return 2
    (start if sys.argv[1] == "start" else stop)(Path.cwd().name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
