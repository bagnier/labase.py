import re

RESERVED = frozenset(
    {
        "auth",
        "profile",
        "console",
        "health",
        "invitations",
        "static",
        "files",
        "api",
        "login",
        "logout",
        "signup",
        "admin",
    }
)

_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def is_valid_handle(handle: str) -> bool:
    return bool(_HANDLE_RE.match(handle)) and len(handle) <= 39


def is_reserved(handle: str) -> bool:
    return handle in RESERVED
