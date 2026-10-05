"""Static files with a ``Cache-Control``, which Starlette leaves out: a fingerprinted URL
(``?v=…``) is ``immutable``, anything else gets the tunable TTL, then ETag revalidation.
"""

from urllib.parse import parse_qs

from starlette.staticfiles import StaticFiles
from starlette.types import Scope

_IMMUTABLE = "public, max-age=31536000, immutable"


class CachingStaticFiles(StaticFiles):
    def __init__(self, *args, max_age: int, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._max_age = max_age

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        if response.status_code < 400:
            response.headers["Cache-Control"] = self._cache_control(scope)
        return response

    def _cache_control(self, scope: Scope) -> str:
        if "v" in parse_qs(scope.get("query_string", b"").decode()):
            return _IMMUTABLE
        if self._max_age > 0:
            return f"public, max-age={self._max_age}"
        return "public, max-age=0, must-revalidate"
