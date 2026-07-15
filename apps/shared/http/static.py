"""Static serving with a public, tunable, content-aware ``Cache-Control``.

Starlette's :class:`StaticFiles` already sends ``ETag`` + ``Last-Modified`` (so a stale
asset is caught by a 304 revalidation), but no ``Cache-Control`` — the browser then
revalidates every asset on every page. This adds the missing header, and makes it *smart*:
a fingerprinted URL (``?v=…``, whose path changes when the content does) is served
``immutable`` so it is never revalidated, while everything else gets a tunable TTL and
falls back to ETag revalidation once it expires.
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
            return _IMMUTABLE  # fingerprinted: the URL changes with the content
        if self._max_age > 0:
            return f"public, max-age={self._max_age}"
        return "public, max-age=0, must-revalidate"  # 0 → revalidate every time (dev)
