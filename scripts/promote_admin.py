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

os.environ.setdefault("ENV_FILE", ".env")

from apps.auth.tests.given_helpers import create_user, find_users, set_admin_role


def promote_admin(email: str, password: str | None) -> None:
    existing = find_users(email)
    if existing:
        uid = existing[0].id
        print(f"User {email} already exists (id={uid}).")
    else:
        password = password or secrets.token_urlsafe(12) + "A1!"
        print(f"Creating user {email}…")
        uid = create_user(email, password)
        print(f"  → auth_user_id={uid}")
        print(f"  → password: {password}")

    set_admin_role(uid)
    print(f"  → promoted {email} to server admin")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a user if missing and promote to admin")
    parser.add_argument("email")
    parser.add_argument("password", nargs="?", default=None)
    args = parser.parse_args()

    promote_admin(args.email, args.password)


if __name__ == "__main__":
    main()
