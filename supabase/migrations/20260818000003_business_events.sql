-- The business journal: an append-only log of typed, immutable facts, written transactionally
-- with the action it records.
--
-- Comes before `profiles` because the signup trigger that seeds a profile also writes this
-- table's first fact (`auth.user_created`), on GoTrue's own transaction.

create table public.business_events (
  id            uuid        primary key default public.uuidv7(),
  created_at    timestamptz not null default now(),
  -- An event names itself in two halves — the app it belongs to and the verb it performs — and
  -- those halves are the stored truth; `kind` is their view. A generated column cannot be
  -- written, so no writer can make the whole disagree with its parts, and a PostgREST client
  -- cannot invent a kind whose prefix claims an app it isn't.
  app_name      text        not null,
  verb          text        not null,
  kind          text        generated always as (app_name || '.' || verb) stored not null,
  -- The emitting app OWNS its phosphor icon and carries it on the fact, so the timeline renders
  -- without `shared` having to map app → icon (a foundation must not name features).
  icon          text        not null default 'circle',
  -- Each correlation key is paired with the readable name it had *then*: the journal outlives its
  -- subjects (a closed account, a deleted or renamed org) and RLS hides a co-member's handle at
  -- read time. Every name is nullable — a system fact has no actor, a server-wide one no org, a
  -- pure-id subject no name, and work outside a request no request.
  user_id       uuid,
  user_name     text,
  org_id        uuid,
  org_name      text,
  -- A weak, table-agnostic reference to the concerned entity: no FK, because it points at
  -- whatever table the fact is about. Every primary key here is a uuid, so it is always one.
  entity_id     uuid,
  entity_name   text,
  request_id    uuid,
  request_name  text,  -- "GET /profile", bound at request time
  ip_address    text,
  payload       jsonb       not null default '{}',
  -- Delivery plumbing, not part of the fact: the cursor the event listener claims on. Left
  -- unmapped by the ORM on purpose (see apps/shared/events/models.py).
  dispatched_at timestamptz
);

create index business_events_created_at_idx on public.business_events (created_at desc);
create index business_events_kind_idx       on public.business_events (kind);
create index business_events_app_name_idx   on public.business_events (app_name);

create index business_events_user_id_idx    on public.business_events (user_id)    where user_id is not null;
create index business_events_org_id_idx     on public.business_events (org_id)     where org_id is not null;
create index business_events_request_id_idx on public.business_events (request_id) where request_id is not null;
create index business_events_entity_id_idx  on public.business_events (entity_id)  where entity_id is not null;

-- Newest-first feeds by actor (profile) and by org (dashboard) — both order by id desc.
create index business_events_user_feed_idx
  on public.business_events (user_id, id desc) where user_id is not null;
create index business_events_org_feed_idx
  on public.business_events (org_id, id desc) where org_id is not null;

-- The listener claims facts not yet fanned out, oldest first.
create index business_events_undispatched_idx on public.business_events (id)
  where dispatched_at is null;

alter table public.business_events enable row level security;

-- A member READS their own actions and every fact of any org they belong to; the console keeps
-- full access through the BYPASSRLS admin session. There is no INSERT grant: the journal is
-- written only through the SECURITY DEFINER function below.
create policy "business_events: self or org member read"
  on public.business_events for select
  using (user_id = auth.uid() or org_id in (select public.user_org_ids()));

grant select on public.business_events to authenticated;
grant select, insert, update, delete on public.business_events to service_role;


-- ── The one writer ──────────────────────────────────────────────────────────────────────────
--
-- The request path records a fact inside its OWN transaction, so the fact commits iff the
-- mutation does. Routing that write through a SECURITY DEFINER function — rather than a raw
-- INSERT grant to `authenticated` — is what stops a PostgREST client on the same role from
-- forging a `todo.created` that the listener would then deliver to the real consumers.
--
-- The function does NOT re-check `user_id = auth.uid()`. That invariant cannot live here: a
-- durable consumer legitimately re-emits on behalf of the original actor, a detached emit runs
-- with no session at all, and seeders attribute to an org's members. Session identity and the
-- fact's actor are decoupled by design; attribution is the emitter's to get right, and the
-- database's job is to be the single writer.
--
-- `kind` stays generated and `id` / `created_at` keep their column defaults — the function passes
-- none of them, so the journal composes its identity and stamps its clock itself.
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
  p_ip_address text,
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
    entity_id, entity_name, request_id, request_name, ip_address, payload
  ) values (
    p_app_name, p_verb, p_icon, p_user_id, p_user_name, p_org_id, p_org_name,
    p_entity_id, p_entity_name, p_request_id, p_request_name, p_ip_address,
    coalesce(p_payload, '{}'::jsonb)
  ) returning id into new_id;
  return new_id;
end;
$$;

-- Only the app's authenticated role may call it (the request path); anon has no business writing
-- the journal. The admin path reaches it through ownership.
revoke all on function public.record_business_event(
  text, text, text, uuid, text, uuid, text, uuid, text, uuid, text, text, jsonb
) from public;
grant execute on function public.record_business_event(
  text, text, text, uuid, text, uuid, text, uuid, text, uuid, text, text, jsonb
) to authenticated;


-- ── Waking the listener ─────────────────────────────────────────────────────────────────────
-- NOTIFY makes delivery ~immediate; the listener still polls as a durability net, since NOTIFY is
-- fire-and-forget (lost when nobody is listening).
create or replace function public.notify_business_event() returns trigger
  language plpgsql as $$
begin
  perform pg_notify('business_event', new.id::text);
  return new;
end;
$$;

create trigger business_events_notify
  after insert on public.business_events
  for each row execute function public.notify_business_event();
