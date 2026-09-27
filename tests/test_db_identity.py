"""The SQL half of the key shape holds the ordering the README's `Identity` principle promises.

Two generators mint primary keys in this tree. The ORM mints one Python-side with
``uuid.uuid7()`` (the ``UUIDPk`` mixin); ``public.uuidv7()`` mints the ones no Python ever
touches — the signup trigger's rows, written inside GoTrue's own transaction where the app has
no session to join, and *every* row of ``business_events``, whose single writer
``record_business_event`` passes no id and so falls to the column default.

That last one is what makes ordering load-bearing rather than decorative: the event listener reads
``business_events.id`` as a cursor (``facts_above_cursor``'s ``id > cursor``), so a key sorting
below the one minted before it is a fact the cursor steps straight over.

Read against the live stack, because the property belongs to the SQL function rather than to
anything the ORM declares about it.
"""

from collections.abc import AsyncIterator
from itertools import pairwise

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from apps.shared.settings.env import get_technical_settings

# The generator answers some five hundred times per millisecond on this stack, so a burst an
# order of magnitude past that leaves most consecutive pairs sharing one millisecond — which is
# exactly where the 48-bit timestamp stops separating two keys and the bits below it have to.
_BURST = 2000

# Ordered by the series index, never by the key itself: the question *is* whether minting order
# and sort order are the same thing.
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
