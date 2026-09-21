-- The pieces every other migration leans on: one key shape, one updated_at rule, one app role.
--
-- File order in this directory is dependency order, not chronology. `organizations` comes second
-- because the RLS helpers it defines gate almost every table; `business_events` comes before
-- `profiles` because the signup trigger that seeds a profile also writes the first fact.

-- Nothing is granted by default. Supabase's default privileges hand `anon` and `authenticated`
-- every privilege on each new table and EXECUTE on each new function in `public`, so the
-- publishable key would reach whatever a migration forgets to lock. Revoked before the first
-- object: the grants the migrations state are the whole of what an API role holds
-- (tests/test_db_privileges.py). EXECUTE to PUBLIC is Postgres' own global default, which a
-- per-schema revoke cannot lift.
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on functions from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges revoke execute on functions from public;

-- One key shape for the whole schema: a time-ordered UUIDv7. Every table's `id` defaults to it, so
-- a primary key is globally unique (no shared sequence, safe across instances) *and* monotonic —
-- which the append-only stores rely on as a cursor (the event listener claims on
-- `business_events.id`, the issue detail pages page on `issue_occurrences.id`). Security tokens
-- keep `gen_random_uuid()` on purpose (unguessable, no embedded timestamp).
--
-- No pgcrypto: `gen_random_uuid()` is core on PG 17, and it supplies every random bit needed here.
-- Time-ordered *within* a millisecond as well as across one, because the 12 bits RFC 9562 calls
-- `rand_a` carry the fraction of the millisecond rather than noise — the RFC's third method, and
-- what PostgreSQL 18's native `uuidv7()` puts there. Left random, those bits decide the order of
-- every pair of keys minted inside the same millisecond, which is a coin toss some five hundred
-- times per millisecond on this hardware; `business_events.id` is read as a cursor, so that toss
-- is a fact the listener steps over. Python 3.14's `uuid.uuid7()`, used on the ORM write path,
-- reaches the same ordering by a different route (a 42-bit counter).
create or replace function public.uuidv7()
returns uuid language plpgsql volatile as $$
declare
  -- Read once: the millisecond and the fraction below it have to describe the same instant, or a
  -- key carries one millisecond's stamp beside the next one's fraction — an inversion per boundary.
  us     bigint := (extract(epoch from clock_timestamp()) * 1000000)::bigint;
  -- One random uuid for the whole key: the 62 bits of `rand_b`, plus the 6 the variant leaves free.
  canvas bytea  := uuid_send(gen_random_uuid());
  -- Microseconds within the millisecond, rescaled over the 4096 steps `rand_a` can hold.
  sub    int    := (us % 1000) * 4096 / 1000;
begin
  return encode(
    set_byte(
      set_byte(
        set_byte(
          -- bytes 0-5: the 48-bit millisecond, big-endian — the low 6 of an 8-byte bigint.
          overlay(canvas placing substring(int8send(us / 1000) from 3) from 1 for 6),
          -- byte 6: version 7 in the high nibble (0x70), `rand_a`'s top 4 bits under it.
          6, 112 + (sub >> 8)
        ),
        -- byte 7: `rand_a`'s low 8 bits.
        7, sub & 255
      ),
      -- byte 8: variant 10 in the top 2 bits, the canvas's own randomness in the remaining 6.
      8, 128 + (get_byte(canvas, 8) & 63)
    ),
    'hex'
  )::uuid;
end;
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

-- The role the application's user connection takes on: `app_rls`, a member of `authenticated`, so
-- every policy and grant written for `authenticated` applies to it too. PostgREST runs a signed-in
-- request on `authenticated` itself, so what only the server may write (the queue, the journal) is
-- granted to `app_rls` alone — a JWT can name `authenticated`, never `app_rls`. The admin connection
-- uses `postgres` (BYPASSRLS), which may take it on for the RLS tests.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_rls') then
    create role app_rls;
  end if;
end
$$;

grant authenticated to app_rls;
grant app_rls to postgres;

-- The role the application's user connection logs in as, with no inherited privileges of its own.
-- Closed here: a password in the repository is known to every clone. Each environment opens it
-- with a secret of its own (`make env` locally, docs/production.md otherwise). A role outlives a
-- database reset, hence the alter on an existing one too.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_user') then
    create role app_user;
  end if;
end
$$;

alter role app_user noinherit nologin password null;

grant app_rls to app_user;

grant usage on schema public to authenticated;


-- Whether an account enrolled a verified authenticator: what decides that its `aal1` token stops
-- short of a sign-in. Read while the request's identity is still being established, so on the
-- app's connection before any claims exist — `auth.mfa_factors` is GoTrue's, and no policy speaks
-- for it. Executable by `app_rls` alone.
create function public.second_factor_enrolled(p_user_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from auth.mfa_factors
     where user_id = p_user_id and factor_type = 'totp' and status = 'verified'
  )
$$;

revoke all on function public.second_factor_enrolled(uuid) from public;
grant execute on function public.second_factor_enrolled(uuid) to app_rls;
