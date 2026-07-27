-- C4: the trail's only writer becomes a controlled function; the raw INSERT capability is retired.
--
-- Until now the request path recorded a business event by INSERTing straight into
-- `business_events` on the caller's own RLS (`authenticated`) session — atomic with the mutation,
-- but resting on `grant insert ... to authenticated` + a `self-attributed insert` policy. A
-- PostgREST client, being the same `authenticated` role, could drive that INSERT just as well:
-- forge a `todo.created` with any payload and any scoping, and the tailer would deliver that
-- fabricated fact to the real consumers. The type system already refuses a malformed or
-- secret-bearing event (C3); this closes the door the same fact could still walk through at the
-- SQL edge — WITHOUT breaking atomic request-path emit.
--
--   1. `record_business_event(...)` (SECURITY DEFINER) inserts the row as its owner, so a caller
--      needs no table INSERT grant. The request session still calls it inside its own
--      transaction, so the fact still commits iff the mutation does — atomicity is untouched.
--   2. It enforces self-attribution itself — a caller acting as a user (a JWT is present) may only
--      record its own `user_id` — so the guarantee the dropped policy carried lives on, in one
--      validated place. The admin/background path runs with no JWT (`auth.uid()` is null) and
--      attributes freely, exactly as the BYPASSRLS session did before.
--   3. The raw `grant insert` + the `self-attributed insert` policy are dropped: `authenticated`
--      can no longer POST /rest/v1/business_events at all. The admin path (signup trigger,
--      detached emit, test seeders) never leaned on that grant and is unaffected.
--
-- `kind` stays generated and `id`/`created_at` keep their column defaults — the function passes
-- none of them, so the trail composes its identity and stamps its clock exactly as before.
--
-- CREATE OR REPLACE so every schema clone (scripts/provision_schema.py dumps public, rewriting
-- `public.` -> `<schema>.`) inherits the function and its `public.business_events` target as
-- `<schema>.business_events`, the same way the signup trigger's body is carried.

create or replace function public.record_business_event(
  p_app_name text,
  p_verb text,
  p_icon text,
  p_user_id uuid,
  p_user_name text,
  p_org_id uuid,
  p_org_name text,
  p_entity_id uuid,
  p_entity_name text,
  p_request_id uuid,
  p_request_name text,
  p_ip text,
  p_payload jsonb
) returns uuid
  language plpgsql
  security definer
  set search_path = ''
as $$
declare
  new_id uuid;
begin
  -- Self-attribution, mirroring the dropped `self-attributed insert` policy: a caller acting as a
  -- user may only record a fact attributed to itself. `auth.uid()` is null on the admin/background
  -- path (no JWT), which is trusted to attribute freely — the signup fact is the user's own, a
  -- seeder attributes to the org's members.
  if auth.uid() is not null and p_user_id is distinct from auth.uid() then
    raise exception 'business event actor % is not the caller %', p_user_id, auth.uid()
      using errcode = 'check_violation';
  end if;
  insert into public.business_events (
    app_name, verb, icon, user_id, user_name, org_id, org_name,
    entity_id, entity_name, request_id, request_name, ip, payload
  ) values (
    p_app_name, p_verb, p_icon, p_user_id, p_user_name, p_org_id, p_org_name,
    p_entity_id, p_entity_name, p_request_id, p_request_name, p_ip, coalesce(p_payload, '{}'::jsonb)
  ) returning id into new_id;
  return new_id;
end;
$$;

-- Only the app's authenticated role may call it (the request path); anon has no business writing
-- the trail. The admin/superuser path reaches it through ownership.
revoke all on function public.record_business_event(
  text, text, text, uuid, text, uuid, text, uuid, text, uuid, text, text, jsonb
) from public;
grant execute on function public.record_business_event(
  text, text, text, uuid, text, uuid, text, uuid, text, uuid, text, text, jsonb
) to authenticated;

-- Retire the raw writer: the function is now the one path a non-admin write can take.
drop policy if exists "business_events: self-attributed insert" on public.business_events;
revoke insert on public.business_events from authenticated;
