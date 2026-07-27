-- The request correlation key becomes a whole uuid, and gains the readable name its siblings have.
--
-- `request_id` was truncated to 8 hex chars at the source. That is 32 bits: a birthday collision
-- lands around 77k requests, after which two unrelated requests share an id — and the Logs screen
-- correlates on exactly that value, so filtering on one would silently merge both traces. The id is
-- now stored whole and shortened only for display (`_short`), which is where a short id helps.
--
-- `request_name` ("GET /profile") closes the last asymmetry among the correlation keys: `user_id`
-- has `user_name`, `org_id` has `org_name`, `entity_id` has `entity_name`. A request id could only
-- be resolved to a route while the firehose still held that request's lines — and the firehose is a
-- recent window of files, so past its retention the id was opaque for good.

-- Legacy 8-char values: pad them into a well-formed uuid so the prefix an admin may have noted down
-- still reads the same on screen (`_short` shows those very 8 chars). The zeroed suffix marks them
-- as historical rather than genuine uuids.
update public.business_events
   set request_id = request_id || '-0000-0000-0000-000000000000'
 where request_id ~ '^[0-9a-fA-F]{8}$';

-- Anything else that cannot be a uuid (hand-written rows, fixtures) loses its id rather than
-- failing the cast: an unparseable correlation key correlates nothing anyway.
update public.business_events
   set request_id = null
 where request_id is not null
   and request_id !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$';

alter table public.business_events
  alter column request_id type uuid using nullif(request_id, '')::uuid;

alter table public.business_events
  add column if not exists request_name text;

-- The partial index was built on the text column; rebuild it on the uuid one.
drop index if exists public.business_events_request_id_idx;
create index business_events_request_id_idx
  on public.business_events (request_id)
  where request_id is not null;
