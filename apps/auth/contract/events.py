"""Auth's public event — emitted once a new auth user exists.

The org context reacts to this (creating the user's personal org and scheduling the
downstream ``OrgCreated`` seeding event). Auth stays ignorant of who listens.
``access_token`` is ``None`` when email confirmation is pending; the org context skips
seeding in that case and picks it up when the confirmation callback fires.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class UserCreated:
    user_id: str
    email: str
    access_token: str | None
