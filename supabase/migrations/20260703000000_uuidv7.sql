-- One key shape for the whole schema: a time-ordered UUIDv7. Every table's `id` defaults to it, so
-- a primary key is globally unique (no shared sequence, safe across instances) *and* monotonic —
-- which the append-only stores rely on as a cursor (business_events dispatch/feeds, error_events
-- pagination). Defined first (earliest migration) so every later CREATE can reference it as a column
-- default. Security tokens keep `gen_random_uuid()` on purpose (unguessable, no embedded timestamp).
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
