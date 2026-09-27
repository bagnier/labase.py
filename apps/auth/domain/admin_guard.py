"""The last-admin invariant: the server must always keep at least one admin.

Shared by every path that can make an admin stop being one — a console revoke, the admin's own
account deletion, a console disable — so the rule is stated once rather than re-guessed at each
call site.
"""


class LastAdminViolation(Exception):
    """The action would leave the server with no admin."""


def ensure_not_last_admin(*, removes_admin: bool, target_is_admin: bool, admin_count: int) -> None:
    if removes_admin and target_is_admin and admin_count <= 1:
        raise LastAdminViolation("The server must keep at least one admin")
