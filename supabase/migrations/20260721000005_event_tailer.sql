-- The async event listener: a background reader of the business_events journal fans each fact to
-- its registered consumers over the task queue. Two schema changes support it.
--
--   1. `consumed` re-keys on the business_events id (a uuid7 the listener dispatches from) — the
--      same shape the emit-time outbox uses. The ledger is disposable — a dropped entry costs
--      at most one redundant re-delivery — so recreate it rather than migrate values.
--   2. A NOTIFY trigger wakes the listener the instant a fact commits, so delivery is ~immediate;
--      it still polls as a durability net, since NOTIFY is fire-and-forget (lost with no listener).

drop table if exists public.consumed;
create table public.consumed (
  topic       text        not null,
  event_id    uuid        not null,   -- the business_events.id the consumer processed
  consumed_at timestamptz not null default now(),
  primary key (topic, event_id)
);
alter table public.consumed enable row level security;
grant insert on public.consumed to authenticated;
create policy consumed_insert on public.consumed
  for insert to authenticated with check (true);

create or replace function public.notify_business_event() returns trigger
  language plpgsql as $$
begin
  perform pg_notify('business_event', NEW.id::text);
  return NEW;
end;
$$;

create trigger business_event_notify
  after insert on public.business_events
  for each row execute function public.notify_business_event();
