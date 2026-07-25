-- Error tracking (Sentry-as-Postgres brick): thousands of events deduped into
-- few groups via stack fingerprinting, with a lifecycle (new → unresolved →
-- resolved → regressed). Server-level admin data: no grants to authenticated,
-- RLS enabled with no policies — same posture as audit_logs.
create table public.error_groups (
  id                  uuid primary key default public.uuidv7(),
  fingerprint         text not null unique,
  title               text not null,
  status              text not null default 'new',
  count               bigint not null default 0,
  first_seen          timestamptz not null default now(),
  last_seen           timestamptz not null default now(),
  first_version       text not null default 'dev',
  last_version        text not null default 'dev',
  resolved_in_version text,
  version             integer not null default 1,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create trigger error_groups_updated_at
  before update on public.error_groups
  for each row execute procedure public.set_updated_at();

create index error_groups_last_seen_idx on public.error_groups (last_seen desc);

create table public.error_events (
  id         uuid primary key default public.uuidv7(),
  group_id   uuid not null references public.error_groups(id) on delete cascade,
  created_at timestamptz not null default now(),
  -- stack, request path/method, user_id, org, request_id — the request_id pivots
  -- each event to its correlated structlog lines, a link SaaS trackers can't offer.
  context    jsonb not null default '{}'
);

-- id is uuid7 (time-ordered), so (group_id, id desc) stays a valid newest-first cursor index.
create index error_events_group_idx on public.error_events (group_id, id desc);

alter table public.error_groups enable row level security;
alter table public.error_events enable row level security;

grant select, insert, update, delete on public.error_groups to service_role;
grant select, insert, update, delete on public.error_events to service_role;
