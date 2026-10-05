"""Create a user if missing, then promote them to server admin.

Usage:
    uv run python scripts/promote_admin.py <email> [<password>]

Idempotent. A missing user is created, confirmed, with the given password or a printed generated
one. The role reaches the JWT at the next sign-in.
"""

import argparse
import os
import secrets
import sys
from pathlib import Path

import httpx

os.environ.setdefault("ENV_FILE", ".env")

from apps.auth.tests.given_helpers import create_user, find_users, set_admin_role
from apps.shared.settings.env import get_technical_settings
from scripts.envfile import apply_host_overrides


def promote_admin(email: str, password: str | None) -> None:
    # Runs on the host, where the app container's `host.docker.internal` does not resolve.
    apply_host_overrides(Path(os.environ["ENV_FILE"]))
    existing = find_users(email)
    if existing:
        uid = existing[0].id
        print(f"User {email} already exists (id={uid}).")
    else:
        password = password or secrets.token_urlsafe(12) + "A1!"
        print(f"Creating user {email}…")
        uid = create_user(email, password)
        print(f"  → user_id={uid}")
        print(f"  → password: {password}")

    set_admin_role(uid)
    print(f"  → promoted {email} to server admin")
    # Said, because an open session lacks the role and would look like a failed promotion.
    print("  → sign out and back in: the claim only reaches the session on the next sign-in")


def _unreachable(exc: httpx.ConnectError) -> None:
    """An unreachable GoTrue: the URL tried and an override, not a traceback."""
    url = get_technical_settings().supabase_api_url
    print(f"Cannot reach GoTrue at {url} ({exc}).", file=sys.stderr)
    print(
        "Point this run at a reachable GoTrue instead, e.g.:\n"
        "  SUPABASE_API_URL=http://127.0.0.1:54321 make promote-admin "
        "ENV_FILE=.env EMAIL=you@example.com",
        file=sys.stderr,
    )
    raise SystemExit(1)


def main_with_args(email: str, password: str | None) -> None:
    try:
        promote_admin(email, password)
    except httpx.ConnectError as exc:
        _unreachable(exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a user if missing and promote to admin")
    parser.add_argument("email")
    parser.add_argument("password", nargs="?", default=None)
    args = parser.parse_args()

    main_with_args(args.email, args.password)


if __name__ == "__main__":
    main()
