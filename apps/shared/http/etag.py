"""Conditional-GET (ETag) support for fully-rendered responses.

A reader-facing page is assembled from many inputs — the page row, the nav, the CSS build
version, the viewer's auth state — so we validate on the rendered bytes rather than any single
upstream field: the hash captures every input for free. Browsers revalidate transparently via
their HTTP cache, so this works for both plain navigation and HTMX-boosted fetches.

If these pages ever become auth-invariant and CDN-fronted, switch `_CACHE_CONTROL` to
``public`` and add ``Vary: Cookie``; today bodies vary by the auth cookie so we keep them
``private``.
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
    """Tag an already-rendered response with a content ETag and revalidation headers.

    Returns a bare ``304 Not Modified`` when the client already holds the current version
    (its ``If-None-Match`` matches), otherwise attaches ``ETag`` + ``Cache-Control`` to
    ``response`` and returns it. Call at the return site with a rendered response — a
    ``TemplateResponse``'s body is available right after construction.
    """
    etag = f'"{hashlib.blake2b(response.body, digest_size=16).hexdigest()}"'
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": _CACHE_CONTROL})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = _CACHE_CONTROL
    return response
