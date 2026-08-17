-- C4: the journal's only writer becomes a controlled function; the raw INSERT is retired.
--
-- Until now the request path recorded a business event by INSERTing straight into
-- `business_events` on the caller's own RLS (`authenticated`) session — atomic with the mutation,
-- but resting on `grant insert ... to authenticated` + a `self-attributed insert` policy. A
-- PostgREST client, being the same `authenticated` role, could drive that INSERT just as well:
-- forge a `todo.created` with any payload and any scoping, and the listener would deliver that
-- fabricated fact to the real consumers.
--
-- Route every write through one SECURITY DEFINER function and retire the raw grant, WITHOUT
-- breaking atomic request-path emit:
--
--   1. `record_business_event(...)` inserts the record as its owner, so a caller needs no table
--      INSERT grant. The request session still calls it inside its own transaction, so the fact
--      still commits iff the mutation does — atomicity is untouched.
--   2. The raw `grant insert` + the `self-attributed insert` policy are dropped: `authenticated`
--      can no longer POST /rest/v1/business_events at all — the arbitrary-row capability the plan
--      set out to remove is gone. The admin path (signup trigger, detached emit, test seeders)
--      never leaned on that grant and is unaffected.
--
-- The function does NOT re-check `user_id = auth.uid()`. That invariant cannot live here: a
-- business event is a durable fact, and its legitimate emitters routinely attribute it to someone
-- other than the calling session's identity — a durable consumer re-emits on behalf of the
-- original actor (organizations' create-personal-org attributes OrganizationCreated to the new
-- user while running as no one, todo's completion counter reacts to one user's tick), a detached
-- emit runs with no session at all, seeders attribute to an org's members. The session identity
-- and the fact's actor are decoupled by design, so the DB can't equate them. Attribution is the
-- application's to get right (each `emit` names the actor); the DB's job here is to be the single
-- writer, which retiring the raw grant achieves.
--
-- `kind` stays generated and `id`/`created_at` keep their column defaults — the function passes
-- none of them, so the journal composes its identity and stamps its clock exactly as before.
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
-- the journal. The admin/superuser path reaches it through ownership.
revoke all on function public.record_business_event(
  text, text, text, uuid, text, uuid, text, uuid, text, uuid, text, text, jsonb
) from public;
grant execute on function public.record_business_event(
  text, text, text, uuid, text, uuid, text, uuid, text, uuid, text, text, jsonb
) to authenticated;

-- Retire the raw writer: the function is now the one path a non-admin write can take.
drop policy if exists "business_events: self-attributed insert" on public.business_events;
revoke insert on public.business_events from authenticated;
