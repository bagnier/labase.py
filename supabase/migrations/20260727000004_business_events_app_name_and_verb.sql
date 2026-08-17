-- `kind` stops being a string to re-split: the journal stores the two halves it is made of.
--
-- An event names itself in two parts — the app it belongs to and the verb it performs — and the
-- class composes `kind` from them (`app_name` + "." + `verb`). The table stored only the composed
-- string, so every reader that needed a half had to take it back apart: the activity timeline
-- recomputed the verb (`kind.split(".", 1)[-1]`) and the app (`[0]`), the deep-link map keyed on
-- the app segment, the console's log viewer derived its per-app axis the same way, and the journal's
-- own app filter was a `like 'todo.%'` prefix scan.
--
-- Here the halves become the stored truth and `kind` becomes their *view*: a stored generated
-- column. Three consequences worth stating:
--
--   1. Nothing that reads `kind` changes. It is still a real, indexed column — the JSON response,
--      the CSV/NDJSON exports, the templates and the catalog lookup that rebuilds a typed event
--      from a row all keep working on the same values.
--   2. The invariant `kind = app_name || '.' || verb` becomes structural. It was a Python test
--      (`test_every_kind_is_exactly_its_app_and_verb`); the schema can hold it itself, and a
--      generated column cannot be written at all — so no writer can make the halves disagree with
--      the whole.
--   3. The `self-attributed insert` policy still applies, and a PostgREST client now supplies the
--      two halves instead of one dotted string: it can no longer invent a `kind` whose prefix
--      claims an app it isn't.

-- ── The halves, backfilled from the whole ───────────────────────────────────────────────────
alter table public.business_events
  add column if not exists app_name text,
  add column if not exists verb     text;

-- A dotless kind cannot be produced by any writer (the class derives it from two non-empty
-- halves, and the signup trigger writes a literal). If one exists it is hand-written data, and
-- guessing its split would silently rewrite history — fail loudly and let a human decide.
do $$
begin
  if exists (select 1 from public.business_events where kind not like '%.%') then
    raise exception 'business_events holds a kind with no "." — split it by hand before migrating';
  end if;
end $$;

-- `split_part` for the app, the *remainder* for the verb: a verb is everything past the first dot,
-- so this stays exact even if one ever carries a dot of its own.
update public.business_events
   set app_name = split_part(kind, '.', 1),
       verb     = substr(kind, strpos(kind, '.') + 1)
 where app_name is null;

alter table public.business_events
  alter column app_name set not null,
  alter column verb     set not null;

-- ── `kind` becomes the view over them ───────────────────────────────────────────────────────
-- A column cannot be converted to generated in place: drop and recreate, which takes its index
-- with it.
drop index if exists public.business_events_kind_idx;
alter table public.business_events drop column kind;
alter table public.business_events
  add column kind text generated always as (app_name || '.' || verb) stored;
-- Both inputs are NOT NULL and `||` over them cannot yield NULL, so the constraint only records
-- what the expression already cannot violate — the same reason pages.search_vector carries it.
alter table public.business_events alter column kind set not null;
create index business_events_kind_idx on public.business_events (kind);

-- The per-app filter (console browser, log viewer) was a prefix scan on the composed string; it is
-- now an equality on a column of its own.
create index business_events_app_name_idx on public.business_events (app_name);

-- ── The one writer that spells a kind out ───────────────────────────────────────────────────
-- The signup trigger inserts the fact on GoTrue's own transaction, and `kind` is no longer
-- insertable — so it must be rewritten here or every signup fails on the next INSERT (the same
-- rewrite the entity_id and drop-level migrations each had to make). CREATE OR REPLACE so every
-- schema clone (scripts/provision_schema.py dumps public) inherits the fixed body.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (auth_user_id, email, handle)
    values (new.id, new.email, null) on conflict do nothing;
  insert into public.business_events (app_name, verb, icon, user_id, entity_id, payload)
    values ('auth', 'user_created', 'user-plus', new.id, new.id,
            jsonb_build_object('email', new.email));
  begin
    insert into test.profiles (auth_user_id, email, handle)
      values (new.id, new.email, null) on conflict do nothing;
  exception when undefined_table then null;
  end;
  return new;
end;
$$;
