-- Durable task queue — the async substrate every Postgres-as-X brick builds on.
-- Claimed with FOR UPDATE SKIP LOCKED so N app instances never double-process.
--
-- Access: app roles may only enqueue (outbox write inside their own business
-- transaction); claiming, completing and retrying are admin-connection work.
create table public.task_queue (
  id                bigserial   primary key,
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

grant insert on public.task_queue to authenticated;
grant usage on sequence public.task_queue_id_seq to authenticated;
create policy task_queue_enqueue on public.task_queue
  for insert to authenticated with check (true);
