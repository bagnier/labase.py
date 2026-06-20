import re

# Reserved slugs are claimed at composition time: each context claims its own via
# ``host.reserve(...)`` in its ``contract/integration.py:register`` (and main claims the
# infra-owned ``static``/``api``). The registry starts empty — no central hardcoded list.
_reserved: set[str] = set()


def reserve(*slugs: str) -> None:
    _reserved.update(slugs)


_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def is_valid_handle(handle: str) -> bool:
    return bool(_HANDLE_RE.match(handle)) and len(handle) <= 39


def is_reserved(handle: str) -> bool:
    return handle in _reserved


def validate_handle(handle: str) -> tuple[int, str] | None:
    """Return (status_code, error_message) if invalid, None if valid."""
    if not handle:
        return 422, "Handle cannot be empty."
    if not is_valid_handle(handle):
        return 422, "Handle must be lowercase alphanumeric with hyphens, max 39 chars."
    if is_reserved(handle):
        return 422, f"'{handle}' is a reserved name."
    return None
