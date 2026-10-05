"""Conditional GET on a rendered response. The ETag hashes the rendered bytes, which covers every
input of the page (row, nav, CSS build, the viewer's auth state).

``private``: bodies vary by the auth cookie. A CDN-fronted, auth-invariant page would need
``public`` and ``Vary: Cookie``.
"""

import hashlib

from fastapi import Request
from fastapi.responses import Response

_CACHE_CONTROL = "private, no-cache"


def _matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    candidates = {token.strip() for token in if_none_match.split(",")}
    return "*" in candidates or etag in candidates


def with_etag(request: Request, response: Response) -> Response:
    """``304`` if ``If-None-Match`` matches, else ``response`` with its ``ETag``. Call it with a
    rendered response: a ``TemplateResponse`` has its body once constructed."""
    etag = f'"{hashlib.blake2b(response.body, digest_size=16).hexdigest()}"'
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": _CACHE_CONTROL})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = _CACHE_CONTROL
    return response
