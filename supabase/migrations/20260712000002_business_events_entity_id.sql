-- Make the *concerned entity* first-class on the business-events journal, the way org_id and
-- request_id already are (20260708000001), so the unified logs viewer (apps/logs) can filter and
-- correlate every event of one todo / page / file — not just those of one org or one request.
-- Until now the id lived only inside `payload` (unindexed, and absent from non-CRUD events).
-- Nullable + backfill-free: rows that never carried one stay null; heterogeneous ids (int pks,
-- uuids, page slugs) share one text column.
alter table public.business_events add column entity_id text;

create index business_events_entity_id_idx
  on public.business_events (entity_id) where entity_id is not null;
