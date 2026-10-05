"""The server keeps at least one admin; checked by every path that can remove one."""


class LastAdminViolation(Exception):
    """The action would leave the server with no admin."""


def ensure_not_last_admin(*, removes_admin: bool, target_is_admin: bool, admin_count: int) -> None:
    if removes_admin and target_is_admin and admin_count <= 1:
        raise LastAdminViolation("The server must keep at least one admin")
