-- The pieces every other migration leans on: one key shape, one updated_at rule, one app role.
--
-- Files run in dependency order: `organizations` defines the RLS helpers; `business_events`
-- precedes `profiles`, whose signup trigger writes the first fact.

-- Nothing granted by default: Supabase would hand the API roles everything a migration forgets
-- to lock. The stated grants are all an API role holds (tests/test_db_privileges.py). EXECUTE to
-- PUBLIC is a global default a per-schema revoke cannot lift.
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on functions from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges revoke execute on functions from public;

-- Every `id` defaults to a UUIDv7, used as a cursor (the listener on `business_events.id`, issue
-- pages on `issue_occurrences.id`); security tokens stay `gen_random_uuid()`.
--
-- Ordered within a millisecond too: `rand_a` carries the millisecond's fraction (RFC 9562 method
-- 3, as PG 18's `uuidv7()`). Random, it would misorder same-millisecond keys and the listener
-- would skip facts. Python's `uuid.uuid7()` orders with a counter instead.
create or replace function public.uuidv7()
returns uuid language plpgsql volatile as $$
declare
  -- Read once, so the millisecond and its fraction describe the same instant.
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

-- Stamps every `updated_at`, whoever writes (ORM, PostgREST, psql).
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- `app_rls`, the app's user role, inherits `authenticated`; what only the server writes (queue,
-- journal) is granted to it alone, since a JWT can name `authenticated`, never `app_rls`.
-- `postgres` (BYPASSRLS) may take it on for the RLS tests.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_rls') then
    create role app_rls;
  end if;
end
$$;

grant authenticated to app_rls;
grant app_rls to postgres;

-- The app's login role, without a password: one in the repository is known to every clone. Each
-- environment sets its own (`make env`, docs/production.md). Altered too, as a role outlives a reset.
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


-- Whether an account enrolled a verified authenticator (then its `aal1` token is no sign-in).
-- Read before any claims exist, and `auth.mfa_factors` has no policy. `app_rls` alone.
create function public.second_factor_enrolled(p_user_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from auth.mfa_factors
     where user_id = p_user_id and factor_type = 'totp' and status = 'verified'
  )
$$;

revoke all on function public.second_factor_enrolled(uuid) from public;
grant execute on function public.second_factor_enrolled(uuid) to app_rls;
