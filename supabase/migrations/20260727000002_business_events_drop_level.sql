-- `level` leaves the business trail. It belongs to logs.
--
-- A log level answers "how much should an operator care about this trace". A business fact has no
-- severity — it happened. The column was a `ClassVar` on the event class, so its value was constant
-- per `kind` and fully derivable from the `kind` already stored: dropping it removes a redundancy,
-- not information. The 19 events that set "warning" were mixing two opposite things anyway — an
-- attempt that was *refused*, and a privileged action that *succeeded*.
--
-- The console's Logs screen keeps `level` as its own display axis: it merges three heterogeneous
-- sources (the firehose with real structlog levels, this trail, and issue occurrences that are
-- always "error"), so it needs one shared column to sort and facet on. Business rows are now
-- projected at a constant level by the viewer — exactly the pattern issue occurrences already use
-- (`_issue_kwargs` drops the filter, `_from_issue` hardcodes "error"). Nothing changes for the
-- JSON response, the NDJSON/CSV exports or the templates.

alter table public.business_events drop column if exists level;

-- The signup trigger inserts `level` explicitly, so it must be rewritten in the same migration or
-- every signup breaks on the next INSERT. CREATE OR REPLACE so each schema's clone
-- (scripts/provision_schema.py) inherits the fixed body, as the entity_id migration had to do.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (auth_user_id, email, handle)
    values (new.id, new.email, null) on conflict do nothing;
  insert into public.business_events (kind, icon, user_id, entity_id, payload)
    values ('auth.user_created', 'user-plus', new.id, new.id,
            jsonb_build_object('email', new.email));
  begin
    insert into test.profiles (auth_user_id, email, handle)
      values (new.id, new.email, null) on conflict do nothing;
  exception when undefined_table then null;
  end;
  return new;
end;
$$;
