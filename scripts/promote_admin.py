"""Create a user if missing, then promote them to server admin.

Usage:
    uv run python scripts/promote_admin.py <email> [<password>]

Idempotent: an existing user is left as-is and simply (re-)promoted; a missing
user is created (confirmed) with the given password, or a generated one that is
printed to stdout. Promotion sets the admin-only ``app_metadata.role`` claim,
which lands in the JWT on the user's next sign-in.
"""

import argparse
import os
import secrets
import sys

import httpx

os.environ.setdefault("ENV_FILE", ".env")

from apps.auth.tests.given_helpers import create_user, find_users, set_admin_role
from apps.shared.settings.env import get_technical_settings


def promote_admin(email: str, password: str | None) -> None:
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
    # The claim lives in ``app_metadata``, which GoTrue embeds in the *access token* — a session
    # opened before this call carries none of it. Said here because "promoted" with no admin
    # button in the app looks exactly like a promotion that failed.
    print("  → sign out and back in: the claim only reaches the session on the next sign-in")


def _unreachable(exc: httpx.ConnectError) -> None:
    """Answer a host that does not resolve with the one line that fixes it.

    A ``.env`` written for the app container points at ``host.docker.internal``, which resolves
    only inside it — and this script runs on the host, where the same service is on localhost.
    Without this, the failure is forty lines of httpx traceback naming neither the host nor the
    way round it.
    """
    url = get_technical_settings().supabase_api_url
    print(f"Cannot reach GoTrue at {url} ({exc}).", file=sys.stderr)
    print(
        "If that host only resolves inside the app container, point this run at the same "
        "service on the host:\n"
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
