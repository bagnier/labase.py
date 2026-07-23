"""Auth application services — registration use-case.

Sign-up creates the auth user in GoTrue; the ``UserCreated`` fact is recorded at the source by the
``on_auth_user_created`` trigger (``handle_new_user``), atomic with the user row in GoTrue's own
transaction — see migration ``20260723000002``. Its reactions (personal org, admin bootstrap,
welcome seeders) are durable consumers run off the trail. HTTP routers call into here and only map
results/errors to responses.
"""

from apps.auth.domain.service import RegisterResult, register


async def register_user(email: str, password: str) -> RegisterResult:
    """Create the auth user. ``UserCreated`` is recorded by the signup trigger, not here."""
    return await register(email, password)
