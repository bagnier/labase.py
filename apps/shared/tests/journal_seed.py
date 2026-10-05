"""Facts written straight to the journal, through the real writer function, for tests that need
history without declaring an app's events. Test-only: ``tests/meta/test_emit_sites`` keeps any
other way of recording a fact out of ``apps/``.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.models import BusinessEventRecord
from apps.shared.events.repository import EventRepository, _append_record
from apps.shared.persistence.database import admin_session_factory


async def seed_fact_on(session: AsyncSession, record: BusinessEventRecord) -> None:
    """Append ``record`` without committing: a fact in flight, holding its key.

    Completes ``record`` in place as the write path would: pinned names the caller left unset,
    and the ``icon`` and ``payload`` defaults (nothing here flushes)."""
    repo = EventRepository(session)
    if record.user_name is None or record.org_name is None:
        user_name, org_name = await repo.pinned_names(record.user_id, record.org_id)
        record.user_name = record.user_name if record.user_name is not None else user_name
        record.org_name = record.org_name if record.org_name is not None else org_name
    record.icon = record.icon or "circle"
    if record.payload is None:
        record.payload = {}
    await _append_record(session, record)


async def seed_fact(record: BusinessEventRecord) -> None:
    """Append ``record`` and commit, so a listener on another connection sees it. Raises on
    failure: a silent miss would surface far from here."""
    async with admin_session_factory()() as session:
        await seed_fact_on(session, record)
        await session.commit()
