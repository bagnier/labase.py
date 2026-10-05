-- The business journal: an append-only log of typed, immutable facts, written transactionally
-- with the action it records.
--
-- Before `profiles`: its signup trigger writes `auth.user_created`.

create table public.business_events (
  id            uuid        primary key default public.uuidv7(),
  created_at    timestamptz not null default now(),
  -- `kind` is generated from app and verb, so no writer can make it disagree with them.
  app_name      text        not null,
  verb          text        not null,
  kind          text        generated always as (app_name || '.' || verb) stored not null,
  -- The emitting app's icon, so `shared` never maps app → icon.
  icon          text        not null default 'circle',
  -- Each key with its name *then*: the journal outlives its subjects, and RLS hides co-members.
  -- Nullable: a system fact has no actor, a server-wide one no org, a background one no request.
  user_id       uuid,
  user_name     text,
  org_id        uuid,
  org_name      text,
  -- Any table's row, hence no FK.
  entity_id     uuid,
  entity_name   text,
  request_id    uuid,
  request_name  text,  -- "GET /profile", bound at request time
  ip_address    text,
  payload       jsonb       not null default '{}',
  -- The listener's cursor, not part of the fact: unmapped by the ORM.
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

-- A member reads their own facts and their orgs'. No INSERT grant: the writer is below.
create policy "business_events: self or org member read"
  on public.business_events for select
  using (user_id = auth.uid() or org_id in (select public.user_org_ids()));

grant select on public.business_events to authenticated;
-- The secret key only reads it.
revoke all on public.business_events from service_role;
grant select on public.business_events to service_role;


-- ── The one writer ──────────────────────────────────────────────────────────────────────────
--
-- Granted to `app_rls`, not `authenticated`, so a PostgREST client cannot forge a fact for the
-- listener to deliver. No `user_id = auth.uid()` check: consumers emit for the original actor,
-- seeders for members, some emits have no session. Attribution is the emitter's.
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

-- The admin path reaches it through ownership.
revoke all on function public.record_business_event(
  text, text, text, uuid, text, uuid, text, uuid, text, uuid, text, text, jsonb
) from public;
grant execute on function public.record_business_event(
  text, text, text, uuid, text, uuid, text, uuid, text, uuid, text, text, jsonb
) to app_rls;


-- ── Waking the listener ─────────────────────────────────────────────────────────────────────
-- NOTIFY is lost when nobody listens, so the listener also polls.
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
