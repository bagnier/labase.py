-- Pin the readable names onto the trail row, so history outlives the things it describes.
--
-- The trail is an audit record, and its subjects are deletable by design: a user can close their
-- account, an owner can delete an org, and an org can be renamed. Resolving those names at read
-- time therefore fails in the two cases that matter most — a deleted subject renders as a bare
-- uuid, and a renamed org shows its *current* name against a fact from before the rename.
--
-- The principle was already accepted for the actor (denormalized so RLS could not
-- hide *who*), it just lived in the payload JSONB rather than in a column. Promoting it — and
-- adding its two siblings — makes all three filterable and indexable instead of reachable only
-- through a `cast(payload as text) ilike` scan.
--
-- All three stay nullable: absence is a real state. A system fact has no actor, a server-wide fact
-- has no org, and a pure-id subject (an account action) has no name to show.

alter table public.business_events
  add column if not exists user_name  text,
  add column if not exists entity_name text,
  add column if not exists org_name    text;

-- Backfill from where these values already live: the payload. The actor's handle was written
-- there under its old name `actor_name` — read that key, write the new column, so existing history
-- keeps its labels rather than starting blank.
update public.business_events
   set user_name = coalesce(user_name, payload ->> 'actor_name'),
       entity_name = coalesce(entity_name, payload ->> 'entity_name')
 where payload ? 'actor_name' or payload ? 'entity_name';

-- `org_name` has no payload ancestor — resolve it once from the orgs that still exist. Rows whose
-- org was already deleted keep a null name: that history is unrecoverable, which is precisely the
-- loss this column exists to stop from happening again.
update public.business_events e
   set org_name = o.name
  from public.organizations o
 where e.org_id = o.id
   and e.org_name is null;

-- Drop the now-duplicated payload keys: one home per value, and the payload goes back to being
-- only what the event itself declared.
update public.business_events
   set payload = payload - 'actor_name' - 'entity_name'
 where payload ? 'actor_name' or payload ? 'entity_name';
