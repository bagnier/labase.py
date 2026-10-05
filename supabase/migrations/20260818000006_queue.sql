-- The durable task queue, its idempotency ledger, and the shared rate-limit counters.

-- ── task_queue ──────────────────────────────────────────────────────────────────────────────
-- The RLS session only enqueues, in its business transaction; the rest is admin work. Never
-- `authenticated`: a task picks its handler and the identity it runs as.

create table public.task_queue (
  id                uuid        primary key default public.uuidv7(),
  topic             text        not null,
  payload           jsonb       not null default '{}',
  user_id           uuid,               -- RLS convention: run the handler as this user
  recurring_seconds integer,            -- non-null → singleton task, re-enqueued on success
  run_at            timestamptz not null default now(),
  attempts          integer     not null default 0,
  max_attempts      integer     not null default 5,
  locked_at         timestamptz,
  done_at           timestamptz,
  failed_at         timestamptz,
  last_error        text,
  created_at        timestamptz not null default now()
);

create index task_queue_ready_idx on public.task_queue (run_at)
  where done_at is null and failed_at is null;

-- One pending row per recurring topic, whichever instance boots first.
create unique index task_queue_recurring_singleton_idx on public.task_queue (topic)
  where recurring_seconds is not null and done_at is null and failed_at is null;

alter table public.task_queue enable row level security;

grant insert on public.task_queue to app_rls;

create policy "task_queue: app enqueue"
  on public.task_queue for insert to app_rls
  with check (true);


-- ── consumed_events ─────────────────────────────────────────────────────────────────────────
-- Delivery is at-least-once, so a non-idempotent consumer records (consumer, event) here in its
-- own transaction, and a redelivery no-ops. A lost row costs one redelivery.

create table public.consumed_events (
  consumer    text        not null,  -- the registered consumer's queue topic
  event_id    uuid        not null,  -- the business_events.id it processed
  consumed_at timestamptz not null default now(),
  primary key (consumer, event_id)
);

alter table public.consumed_events enable row level security;

grant insert on public.consumed_events to app_rls;

create policy "consumed_events: app mark"
  on public.consumed_events for insert to app_rls
  with check (true);


-- ── rate_limit_counters ─────────────────────────────────────────────────────────────────────
-- Fixed-window counters shared across instances. Admin only: RLS on with no policy.

create table public.rate_limit_counters (
  key          text        not null,
  window_start timestamptz not null,
  count        integer     not null default 1,
  primary key (key, window_start)
);

alter table public.rate_limit_counters enable row level security;
