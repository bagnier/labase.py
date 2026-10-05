-- One retention floor for the partition drop and the row-level DELETE, so they cannot drift
-- apart (#92). Returns the rows deleted.
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
  day        date;
  floor_day  date := (p_today - make_interval(days => p_retention_days))::date;
  part       text;
  dropped    int  := 0;
  stragglers int;
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
        -- DROP is lost for it, and the row-level cleanup below still reaches those rows.
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

  -- Default-partition rows past the floor day. The day, not the instant, which would cut into
  -- the partition just kept.
  delete from public.log_lines where ts < floor_day;
  get diagnostics stragglers = row_count;

  return stragglers;
end;
$$;

revoke all on function public.roll_log_partitions(date, int, int) from public;
