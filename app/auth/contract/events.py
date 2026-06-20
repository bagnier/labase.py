"""Auth's public event — emitted once a new auth user exists.

The org context reacts to this (creating the user's personal org); auth stays ignorant
of who listens. Carries only identity: anything needing the user's access token uses the
downstream ``OrgCreated`` event instead.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class UserCreated:
    user_id: str
    email: str
