"""How auth resolves an ``lbk_...`` bearer token without importing api_keys
(AGENTS: import downward, event upward). Without that app, API keys stop authenticating.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

API_KEY_PREFIX = "lbk_"


@dataclass(frozen=True)
class ApiKeyQuery:
    """A raw bearer token to resolve to an ``AuthenticatedUser``, or ``None``. ``session`` is
    lazy, so the cookie path never opens it."""

    token: str
    session: AsyncSession
