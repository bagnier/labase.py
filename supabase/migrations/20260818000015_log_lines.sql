-- Log lines (Logs-as-Postgres): one row per structlog line, the `logs` source of the console
-- Timeline. Named for what it stores, not for the mechanism that fills it — the log sink is the
-- plumbing (apps/shared/observability/sink.py), the way `task_queue` is filled by the worker and
-- `business_events` by the bus. Comes last because it depends on nothing but `uuidv7()`.
--
-- Why a table and not the per-day JSON files this replaces: those were local to each process, so
-- with a second instance the Timeline showed the journal and the issues in full (both in Postgres)
-- and only *one instance's* log lines between them. The files survive as the write fallback for
-- when Postgres itself is the thing that is down.
--
-- UNLOGGED and partitioned, which is what makes one-row-per-line affordable:
--
--   * UNLOGGED skips the WAL entirely — the single biggest lever on write throughput. The price
--     is stated plainly: crash recovery TRUNCATES this table, and it is neither replicated nor in
--     PITR. That is the right trade for exactly this data and no other: stdout already carries
--     the durable copy an aggregator reads, the queue feeding this table is bounded and drops
--     under pressure, and the drain is best-effort by doctrine. Nothing here is a fact — facts go
--     to `business_events`, which is logged, replicated and backed up.
--
--   * RANGE partitioning by day turns retention from a DELETE that leaves dead tuples for VACUUM
--     into an instant DROP of yesterday — the Postgres equivalent of the file rotation this
--     replaced. Inserts also touch one small, hot partition instead of one ever-growing index.
--
-- Server-level admin data: RLS on with no policy, same posture as `issues` and `request_metrics`.

create unlogged table public.log_lines (
  id         uuid        not null default public.uuidv7(),
  -- The instant the line was *written by the caller*, not the instant it reached this table: the
  -- queue between them is drained on an interval, and a reader correlating against a business
  -- fact needs the moment the code spoke. Also the partition key, hence part of the key below.
  ts         timestamptz not null,
  level      text        not null,
  -- The logger that wrote it, which is the app axis the Timeline browses by
  -- (`apps.todo.infra.router` → todo, `sqlalchemy.pool` → sqlalchemy).
  logger     text        not null,
  -- structlog's own word for the trace name (`request.finished`); `event` is not usable as a
  -- column name here without quoting on every read.
  name       text        not null,
  -- Correlation keys as the log context carries them: text, not uuid. A line inherits these from
  -- contextvars, and a caller may bind anything (a seeded fixture, a synthetic id); refusing a
  -- non-uuid would drop the line rather than record it, which is the opposite of the job.
  org_id     text,
  user_id    text,
  request_id text,
  -- Which process wrote it. With one shared table and N instances, a line that cannot say where
  -- it came from makes a single-instance outage look like a global one.
  instance   text        not null,
  -- Everything the line carried beyond the columns above.
  payload    jsonb       not null default '{}',
  -- Postgres requires the partition key in every unique constraint, so the key is the pair. `id`
  -- alone is still unique in practice (uuidv7), and nothing reads a line by primary key anyway —
  -- the Timeline reads by time and by correlation key.
  primary key (id, ts)
) partition by range (ts);

-- Declared on the parent, so every partition — including ones created years from now — inherits
-- them. Newest-first is every read's order, and the cursor the Timeline pages on.
create index log_lines_ts_idx on public.log_lines (ts desc);
create index log_lines_level_idx on public.log_lines (level);
create index log_lines_logger_idx on public.log_lines (logger);

-- Partial, like the journal's: most lines carry none of these.
create index log_lines_org_idx     on public.log_lines (org_id)     where org_id is not null;
create index log_lines_user_idx    on public.log_lines (user_id)    where user_id is not null;
create index log_lines_request_idx on public.log_lines (request_id) where request_id is not null;

-- The safety net. An INSERT whose day has no partition FAILS, which would take logging down
-- exactly when the roll job has stopped running — so everything unclaimed lands here instead.
-- It should stay empty; `roll_log_partitions` works ahead of the clock to keep it that way.
create unlogged table public.log_lines_default partition of public.log_lines default;

alter table public.log_lines enable row level security;

grant select, insert, update, delete on public.log_lines to service_role;


-- ── Rolling the partitions ──────────────────────────────────────────────────────────────────
--
-- Called daily by the `timeline.purge` task, and once below so today exists from the start.
-- Creates the days ahead before they are needed and drops the ones past retention.
--
-- Working *ahead* is not an optimisation, it is the correctness condition: a partition cannot be
-- created for a range the default partition already holds rows for ("would be violated by some
-- row"), so once the roll falls behind for a day, that day belongs to the default partition for
-- good. Hence the exception handler — a day we can no longer claim must not stop the rest of the
-- roll, and its rows are still readable, just not droppable as a unit.
-- `p_today` is passed in rather than read from `current_date`: time in this codebase comes from
-- one clock (apps/shared/clock.py), which is also what lets a test pin it and assert what a
-- retention window actually drops.
create or replace function public.roll_log_partitions(
  p_today date,
  p_retention_days int,
  p_ahead_days int default 2
) returns int
  language plpgsql
  security definer
  set search_path = ''
as $$
declare
  day       date;
  floor_day date := (p_today - make_interval(days => p_retention_days))::date;
  part      text;
  dropped   int  := 0;
begin
  for day in
    select generate_series(p_today, p_today + p_ahead_days, interval '1 day')::date
  loop
    part := 'log_lines_' || to_char(day, 'YYYYMMDD');
    if to_regclass('public.' || part) is null then
      begin
        execute format(
          'create unlogged table public.%I partition of public.log_lines '
          'for values from (%L) to (%L)',
          part, day, day + 1
        );
      exception when others then
        -- The default partition already holds that day. Logging keeps working; only the cheap
        -- DROP is lost for it, and the row-level purge still reaches those rows.
        null;
      end;
    end if;
  end loop;

  for part in
    select c.relname
      from pg_class c
      join pg_inherits i on i.inhrelid = c.oid
     where i.inhparent = 'public.log_lines'::regclass
       and c.relname ~ '^log_lines_[0-9]{8}$'
       and to_date(right(c.relname, 8), 'YYYYMMDD') < floor_day
  loop
    execute format('drop table public.%I', part);
    dropped := dropped + 1;
  end loop;

  return dropped;
end;
$$;

revoke all on function public.roll_log_partitions(date, int, int) from public;

-- Seed today's (and the next days') partitions, so the very first line has somewhere to go that
-- is not the default.
select public.roll_log_partitions(current_date, 30);
