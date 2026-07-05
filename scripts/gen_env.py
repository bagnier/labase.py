"""Generate a local .env from `supabase status -o env`.

Maps the Supabase CLI variable names to the names expected by
``apps.shared.config.TechnicalSettings`` and rewrites the local DB URLs to the
asyncpg driver, splitting the user (app_user, RLS) and service (postgres)
connections. Host-side scripts and the Docker app both reach the stack through
``host.docker.internal`` (see comments in .env.example).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ENV_PATH = Path(".env")
DOCKER_HOST = "host.docker.internal"


def supabase_status() -> dict[str, str]:
    out = subprocess.run(
        ["supabase", "status", "-o", "env"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    values: dict[str, str] = {}
    for line in out.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.isupper() and key.replace("_", "").isalnum():
            values[key] = value.strip().strip('"')
    return values


def to_asyncpg(db_url: str, *, user: str, password: str) -> str:
    # postgresql://postgres:postgres@127.0.0.1:54322/postgres
    _, _, tail = db_url.partition("@")
    host_part = tail.replace("127.0.0.1", DOCKER_HOST)
    return f"postgresql+asyncpg://{user}:{password}@{host_part}"


def build_env(status: dict[str, str]) -> str:
    api_url = status["API_URL"]
    db_url = status["DB_URL"]
    user_url = to_asyncpg(db_url, user="app_user", password="app_user_password")
    service_url = to_asyncpg(db_url, user="postgres", password="postgres")
    lines = [
        f"SUPABASE_API_URL={api_url.replace('127.0.0.1', DOCKER_HOST)}",
        f"SUPABASE_STORAGE_URL={api_url}",
        f"SUPABASE_PUBLISHABLE_KEY={status['PUBLISHABLE_KEY']}",
        f"SUPABASE_SECRET_KEY={status['SECRET_KEY']}",
        f"SUPABASE_DATABASE_USER_URL={user_url}",
        f"SUPABASE_DATABASE_ADMIN_URL={service_url}",
        "LOG_DEBUG=true",
        "COOKIES_SECURE=false",
        "RATE_LIMIT_ENABLED=false",
        f"SMTP_HOST={DOCKER_HOST}",
        "SMTP_PORT=54325",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        status = supabase_status()
    except subprocess.CalledProcessError as exc:
        print(exc.stderr, file=sys.stderr)
        print("Is the local stack running? Try `make db-start`.", file=sys.stderr)
        return 1
    ENV_PATH.write_text(build_env(status))
    print(f"Wrote {ENV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
