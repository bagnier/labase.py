"""Registration (AGENTS: sign-up is a chain of durable reactions). ``UserCreated`` is recorded by
the ``on_auth_user_created`` trigger, in GoTrue's own transaction.
"""

from apps.auth.domain.service import RegisterResult, register


async def register_user(email: str, password: str, client_ip: str | None = None) -> RegisterResult:
    """Create the auth user in GoTrue."""
    return await register(email, password, client_ip)
