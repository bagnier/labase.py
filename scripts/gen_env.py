"""Generate the local .env from `supabase status -o env`: names mapped to ``TechnicalSettings``,
asyncpg URLs for the user (app_user, RLS) and admin (postgres) connections, through
``host.docker.internal`` (see .env.example).

``app_user`` cannot log in after the migrations: this sets its password, the one already in .env
if any, since worktrees share the stack. Merged into an existing .env, so worktree overrides
survive.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import subprocess
import sys
from pathlib import Path

import asyncpg
from sqlalchemy import make_url

from scripts.envfile import merge_env

ENV_PATH = Path(".env")
DOCKER_HOST = "host.docker.internal"
# `secrets.token_urlsafe(32)`'s shape: anything else is replaced. Safe unquoted in a URL and in
# ALTER ROLE.
GENERATED_PASSWORD = re.compile(r"[A-Za-z0-9_-]{43}")


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


def user_password(env_path: Path) -> str:
    """The .env's generated password, else a fresh one."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    for line in lines:
        key, _, value = line.partition("=")
        if key.strip() == "SUPABASE_DATABASE_USER_URL":
            password = make_url(value.strip()).password
            if password is not None and GENERATED_PASSWORD.fullmatch(password):
                return password
    return secrets.token_urlsafe(32)


def to_asyncpg(db_url: str, *, user: str, password: str) -> str:
    # postgresql://postgres:postgres@127.0.0.1:54322/postgres
    _, _, tail = db_url.partition("@")
    host_part = tail.replace("127.0.0.1", DOCKER_HOST)
    return f"postgresql+asyncpg://{user}:{password}@{host_part}"


def build_overrides(status: dict[str, str], password: str) -> dict[str, str]:
    api_url = status["API_URL"]
    db_url = status["DB_URL"]
    user_url = to_asyncpg(db_url, user="app_user", password=password)
    service_url = to_asyncpg(db_url, user="postgres", password="postgres")
    return {
        "SUPABASE_API_URL": api_url.replace("127.0.0.1", DOCKER_HOST),
        "SUPABASE_STORAGE_URL": api_url,
        # Browser-facing: no Docker rewrite. Empty without a Studio, hiding the console's links.
        "SUPABASE_STUDIO_URL": (
            f"{status['STUDIO_URL']}/project/default" if status.get("STUDIO_URL") else ""
        ),
        "SUPABASE_PUBLISHABLE_KEY": status["PUBLISHABLE_KEY"],
        "SUPABASE_SECRET_KEY": status["SECRET_KEY"],
        "SUPABASE_DATABASE_USER_URL": user_url,
        "SUPABASE_DATABASE_ADMIN_URL": service_url,
        "LOG_DEBUG": "true",
        "COOKIES_SECURE": "false",
        "RATE_LIMIT_ENABLED": "false",
        "SMTP_HOST": DOCKER_HOST,
        "SMTP_PORT": "54325",
    }


async def open_user_role(db_url: str, password: str) -> None:
    if not GENERATED_PASSWORD.fullmatch(password):
        raise ValueError("refusing to put a non-generated password into ALTER ROLE")
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(f"alter role app_user login password '{password}'")
    finally:
        await conn.close()


def main() -> int:
    try:
        status = supabase_status()
    except subprocess.CalledProcessError as exc:
        print(exc.stderr, file=sys.stderr)
        print("Is the local stack running? Try `make db-start`.", file=sys.stderr)
        return 1
    password = user_password(ENV_PATH)
    asyncio.run(open_user_role(status["DB_URL"], password))
    merge_env(ENV_PATH, ENV_PATH, build_overrides(status, password))
    print(f"Wrote {ENV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
