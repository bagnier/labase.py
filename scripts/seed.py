"""Seed dev data: one user, one org, a few todos.

Usage:
    uv run python scripts/seed.py
    uv run python scripts/seed.py --email dev@example.com --password Azerty123! --org "My Org"

Idempotent: skips creation if the user already exists.
"""

import argparse
import asyncio
import os
import uuid

os.environ.setdefault("ENV_FILE", ".env")

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.tests.given_helpers import (
    create_user,
    delete_user_if_exists,
    find_users,
    set_admin_role,
)
from app.organizations.infra.repository import OrganizationRepository
from app.shared.config import get_technical_settings
from app.todo.domain.models import TodoItem

_DEFAULT_EMAIL = "dev@labase.dev"
_DEFAULT_PASSWORD = "Devpass123!"
_DEFAULT_ORG = "Dev Org"
_TODOS = ["Read the docs", "Write a test", "Ship it"]


async def seed(email: str, password: str, org_name: str, *, reset: bool) -> None:
    settings = get_technical_settings()

    if reset:
        print(f"Deleting {email}…")
        delete_user_if_exists(email)

    existing = find_users(email)
    if existing:
        print(f"User {email} already exists (id={existing[0].id}), seed skipped.")
        print("Re-run with --reset to recreate from scratch.")
        return

    print(f"Creating user {email}…")
    uid_str = create_user(email, password)
    auth_user_id = uuid.UUID(uid_str)
    print(f"  → auth_user_id={auth_user_id}")

    # First seeded user is the server admin (matches the bootstrap rule for the first registrant).
    set_admin_role(uid_str)
    print("  → promoted to server admin")

    url = settings.database_url_service or settings.database_url
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
    engine = create_async_engine(url, connect_args=connect_args)

    async with engine.begin() as conn, AsyncSession(bind=conn, expire_on_commit=False) as session:
        repo = OrganizationRepository(session)
        org = await repo.create_with_owner(org_name, auth_user_id)
        print(f"  → org '{org.name}' (handle={org.handle}, id={org.id})")

        for i, title in enumerate(_TODOS):
            session.add(TodoItem(user_id=auth_user_id, org_id=org.id, title=title, position=i))

        await session.flush()

    await engine.dispose()
    print(f"\nSeed complete. Sign in with {email} / {password}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed dev data")
    parser.add_argument("--email", default=_DEFAULT_EMAIL)
    parser.add_argument("--password", default=_DEFAULT_PASSWORD)
    parser.add_argument("--org", default=_DEFAULT_ORG)
    parser.add_argument(
        "--reset", action="store_true", help="Delete the existing user before recreating"
    )
    args = parser.parse_args()

    asyncio.run(seed(args.email, args.password, args.org, reset=args.reset))


if __name__ == "__main__":
    main()
