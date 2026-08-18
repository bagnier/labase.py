-- The async substrate every Postgres-as-X brick builds on: a durable task queue, the idempotency
-- ledger its at-least-once delivery needs, and the shared rate-limit counters.

-- ── task_queue ──────────────────────────────────────────────────────────────────────────────
-- Claimed with FOR UPDATE SKIP LOCKED, so N app instances never double-process.
--
-- Access: app roles may only enqueue (an outbox write inside their own business transaction, so
-- a task exists iff that transaction commits); claiming, completing and retrying are admin work.

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

-- id comes from the column default (execute on uuidv7 granted in the foundation) — no sequence
-- to grant.
grant insert on public.task_queue to authenticated;

create policy "task_queue: app enqueue"
  on public.task_queue for insert to authenticated
  with check (true);


-- ── consumed_events ─────────────────────────────────────────────────────────────────────────
-- The idempotency ledger for durable async event consumers.
--
-- Durable fan-out is at-least-once (the listener may re-deliver after a crash between a handler's
-- commit and its task bookkeeping), so a non-idempotent consumer records each (consumer, event)
-- pair it has processed here, in the SAME transaction as its own writes: a retry then sees the
-- row and no-ops, and a rolled-back handler leaves no ledger entry.
--
-- Disposable by design — a lost entry costs at most one redundant re-delivery.

create table public.consumed_events (
  consumer    text        not null,  -- the registered consumer's queue topic
  event_id    uuid        not null,  -- the business_events.id it processed
  consumed_at timestamptz not null default now(),
  primary key (consumer, event_id)
);

alter table public.consumed_events enable row level security;

grant insert on public.consumed_events to authenticated;

create policy "consumed_events: app mark"
  on public.consumed_events for insert to authenticated
  with check (true);


-- ── rate_limit_counters ─────────────────────────────────────────────────────────────────────
-- Shared fixed-window counters, so a limit holds across instances. Written only through the
-- admin connection: no grants, RLS on with no policy (deny-all for the API roles).

create table public.rate_limit_counters (
  key          text        not null,
  window_start timestamptz not null,
  count        integer     not null default 1,
  primary key (key, window_start)
);

alter table public.rate_limit_counters enable row level security;
