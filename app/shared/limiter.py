from collections.abc import Callable
from typing import Any

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.shared.config import get_settings

limiter = Limiter(key_func=get_remote_address)


def rate_limit(limit_string: str) -> Callable[[Any], Any]:
    if get_settings().debug:
        return lambda f: f
    return limiter.limit(limit_string)  # type: ignore[return-value]
