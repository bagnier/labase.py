-- One row per log line, the Timeline's `logs` source, filled by apps/shared/logs/sink.py. A
-- table, so every instance's lines show.
--
--   * UNLOGGED: no WAL, but crash recovery truncates it and it is not replicated. Right for this
--     data only: stdout holds the durable copy, and nothing here is a fact.
--   * Partitioned by day: retention is an instant DROP, not a DELETE leaving work for VACUUM.
--
-- Admin only: RLS on with no policy.

create unlogged table public.log_lines (
  id         uuid        not null default public.uuidv7(),
  -- When the code logged, not when the drain wrote it. The partition key.
  ts         timestamptz not null,
  level      text        not null,
  -- The Timeline's app axis (`apps.todo.infra.router` → todo).
  logger     text        not null,
  -- structlog's `event` (`request.finished`), a name that would need quoting.
  name       text        not null,
  -- Text, not uuid: a caller may bind anything, and a refused value would drop the line.
  org_id     text,
  user_id    text,
  request_id text,
  -- So one instance's outage does not read as everyone's.
  instance   text        not null,
  -- Everything the line carried beyond the columns above.
  payload    jsonb       not null default '{}',
  -- A unique constraint must hold the partition key.
  primary key (id, ts)
) partition by range (ts);

-- On the parent, so every partition inherits them.
create index log_lines_ts_idx on public.log_lines (ts desc);
create index log_lines_level_idx on public.log_lines (level);
create index log_lines_logger_idx on public.log_lines (logger);

-- Partial, like the journal's: most lines carry none of these.
create index log_lines_org_idx     on public.log_lines (org_id)     where org_id is not null;
create index log_lines_user_idx    on public.log_lines (user_id)    where user_id is not null;
create index log_lines_request_idx on public.log_lines (request_id) where request_id is not null;

-- Without it, an INSERT for a day with no partition fails. Kept empty by `roll_log_partitions`.
create unlogged table public.log_lines_default partition of public.log_lines default;

alter table public.log_lines enable row level security;

grant select, insert, update, delete on public.log_lines to service_role;


-- ── Rolling the partitions ──────────────────────────────────────────────────────────────────
--
-- Daily (`timeline.purge`): creates the days ahead, drops those past retention. Ahead, because a
-- partition cannot be created for a day the default partition holds rows for; such a day stays
-- there, which the exception handler absorbs. `p_today` comes from the app's one clock.
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

select public.roll_log_partitions(current_date, 30);
