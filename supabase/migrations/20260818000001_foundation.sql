-- The pieces every other migration leans on: one key shape, one updated_at rule, one app role.
--
-- File order in this directory is dependency order, not chronology. `organizations` comes second
-- because the RLS helpers it defines gate almost every table; `business_events` comes before
-- `profiles` because the signup trigger that seeds a profile also writes the first fact.

-- One key shape for the whole schema: a time-ordered UUIDv7. Every table's `id` defaults to it, so
-- a primary key is globally unique (no shared sequence, safe across instances) *and* monotonic —
-- which the append-only stores rely on as a cursor (the event listener claims on
-- `business_events.id`, the issue detail pages page on `issue_occurrences.id`). Security tokens
-- keep `gen_random_uuid()` on purpose (unguessable, no embedded timestamp).
--
-- Pure core SQL — no pgcrypto: a random uuid supplies the entropy, its first 48 bits overlaid with
-- the current epoch-millisecond, and the version (0111) / variant (10) nibbles set in place. Ordered
-- to the millisecond, which matches Python 3.14's stdlib `uuid.uuid7()` used on the ORM write path.
create or replace function public.uuidv7()
returns uuid language sql volatile as $$
  select encode(
    set_byte(
      set_byte(
        overlay(
          uuid_send(gen_random_uuid())
          placing substring(int8send((extract(epoch from clock_timestamp()) * 1000)::bigint) from 3)
          from 1 for 6
        ),
        6, (b'0111' || get_byte(uuid_send(gen_random_uuid()), 6)::bit(4))::bit(8)::int
      ),
      8, (b'10' || get_byte(uuid_send(gen_random_uuid()), 8)::bit(6))::bit(8)::int
    ),
    'hex'
  )::uuid
$$;

grant execute on function public.uuidv7() to authenticated, anon, service_role;

-- Every `updated_at` in the schema is stamped by this one trigger function, so a write through
-- PostgREST or psql is stamped exactly like a write through the ORM.
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- The role the application's user connection logs in as: `authenticated`, so RLS applies to it,
-- with no inherited privileges of its own. The admin connection uses `postgres` (BYPASSRLS).
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_user') then
    create role app_user noinherit login password 'app_user_password';
  end if;
end
$$;

grant authenticated to app_user;

grant usage on schema public to authenticated;
