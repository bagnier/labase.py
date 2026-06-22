"""Server-admin domain logic — framework-free. The last-admin guard, the server-scope twin of
the organisations' last-owner guard (``ensure_not_last_owner``).
"""


class LastAdminViolation(Exception):
    """Revoking would leave the server with no admin."""


def ensure_not_last_admin(*, is_revoke: bool, target_is_admin: bool, admin_count: int) -> None:
    if is_revoke and target_is_admin and admin_count <= 1:
        raise LastAdminViolation("The server must keep at least one admin")
