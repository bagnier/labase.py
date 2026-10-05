"""``public.uuidv7()`` mints in order (AGENTS: every key is a UUIDv7, every token a UUIDv4): it
keys every fact, and the listener's cursor would skip one sorting below its predecessor.
"""

from collections.abc import AsyncIterator
from itertools import pairwise

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from apps.shared.settings.env import get_technical_settings

# Enough keys to share milliseconds, where the bits below the timestamp must keep the order.
_BURST = 2000

# Ordered by minting, to compare with the keys' own order.
_MINT_BURST_SQL = """
select public.uuidv7() as key
  from generate_series(1, :count) as i
 order by i
"""


@pytest_asyncio.fixture
async def admin_conn() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(get_technical_settings().supabase_database_admin_url)
    try:
        async with engine.connect() as conn:
            yield conn
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_sql_key_generator_never_mints_below_its_previous_key(
    admin_conn: AsyncConnection,
):
    rows = await admin_conn.execute(text(_MINT_BURST_SQL), {"count": _BURST})

    minted = [row.key for row in rows]
    out_of_order = [(before, after) for before, after in pairwise(minted) if after < before]

    assert out_of_order == []
