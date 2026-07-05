"""The seam between auth and the api_keys context — a typed query, no import.

Auth routes `Authorization: Bearer lbk_...` tokens to whoever answers
`ApiKeyQuery` on the bus (the api_keys context registers a handler at mount);
deleting that context simply makes API keys stop authenticating.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

API_KEY_PREFIX = "lbk_"


@dataclass(frozen=True)
class ApiKeyQuery:
    """Resolve a raw bearer token to an AuthenticatedUser (or None).

    Carries the request's admin session (SQLAlchemy sessions are lazy, so the
    cookie path never pays for it): resolution happens pre-auth, where no JWT
    exists yet — the hash lookup is the explicit check.
    """

    token: str
    session: AsyncSession
