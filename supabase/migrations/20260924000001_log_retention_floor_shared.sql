-- #92: the retention floor for `log_lines` was computed twice — once here, in
-- `roll_log_partitions`, and once in `LogRepository.purge` (Python), from the same
-- `retention_days` — with nothing binding the two expressions together. #43's fix made the
-- row-level DELETE agree with the day the roll keeps whole only because both sides happened to
-- use the same arithmetic; an edit to either alone (a grace day, an inclusive bound, a change of
-- unit) would silently reopen it.
--
-- The straggler DELETE moves into this function, next to the `floor_day` it must agree with, so
-- one statement — and one floor — owns both the partition drop and the row-level cleanup.
-- `purge` no longer computes a floor of its own; it just calls this. The return value keeps its
-- prior meaning (the row count a straggler DELETE removed) rather than mixing it with the
-- partition count, whose unit is a table, not a line.
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

  -- The stragglers: rows past the same floor day that a whole-partition DROP above could not
  -- reach — a line dated outside every range, or a day the roll fell behind on, both of which
  -- land in the default partition. Never the exact instant `p_retention_days` ago: that finer
  -- floor falls inside the floor day itself, row-deleting part of the very partition just kept.
  -- `dropped` (the partition count) stays a local count, not part of the return: a table and a
  -- row are different units, and mixing them into one number would report neither honestly.
  delete from public.log_lines where ts < floor_day;
  get diagnostics stragglers = row_count;

  return stragglers;
end;
$$;

revoke all on function public.roll_log_partitions(date, int, int) from public;
