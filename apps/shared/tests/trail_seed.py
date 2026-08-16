"""Seeding the trail directly — for tests that need rows without emitting the events.

Production records a fact exactly one way: ``bus.emit(event, session)``, which takes the caller's
transaction so the fact commits iff the action does. A test often needs the opposite: a row of some
app's kind, without declaring that app's event class, and without a request to hang it on — the
timeline, the logs viewer and the tailer all need history that no test action produced.

So this writes the columns directly, through the same ``record_business_event`` SECURITY DEFINER
function the real write path uses. It lives **in tests** on purpose: a way to record a fact on no
transaction at all is exactly what ``tests/test_emit_sites`` keeps out of ``apps/``, and it stays
out by not being importable from there.

The row *is* the argument: :class:`BusinessEventRecord` already names every column, so the seeder
never re-lists them.
"""

from apps.shared.events.models import BusinessEventRecord
from apps.shared.events.repository._write import _record_row, _WritesEvents
from apps.shared.persistence.database import admin_session_factory


async def seed_fact(row: BusinessEventRecord) -> None:
    """Append ``row`` to the trail on its own admin session, and commit — the arrangement has to
    outlive the request under test, and be visible to a tailer reading on another connection.

    Fills what the real write path fills before writing: the readable names pinned as of now, and
    the ``icon`` column default, which SQLAlchemy applies at flush and nothing here ever flushes.
    The row is a throwaway carrier the caller built for this one write (the same thing
    ``event_to_record`` returns), so it is completed in place.

    A failed write raises: seeding is arranging, and an arrangement that silently did nothing
    surfaces later as an assertion about a page, pointing anywhere but here."""
    async with admin_session_factory()() as session:
        repo = _WritesEvents(session)
        row.user_name, row.org_name = await repo.pinned_names(row.user_id, row.org_id)
        row.icon = row.icon or "circle"
        await _record_row(session, row)
        await session.commit()
