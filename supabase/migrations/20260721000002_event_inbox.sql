-- Event inbox — the idempotency ledger for durable async event consumers.
--
-- Durable fan-out is at-least-once (the poller may re-deliver after a crash between a
-- handler's commit and its task bookkeeping), so a non-idempotent consumer records each
-- (topic, event_id) it has processed here, in the SAME transaction as its own writes:
-- a retry then sees the row and no-ops, and a rolled-back handler leaves no ledger entry.
--
-- Access mirrors task_queue: app roles may only insert (their own consumption mark inside
-- their handler transaction); everything else is admin-connection work.
create table public.consumed (
  topic       text        not null,
  event_id    uuid        not null,
  consumed_at timestamptz not null default now(),
  primary key (topic, event_id)
);

alter table public.consumed enable row level security;

grant insert on public.consumed to authenticated;
create policy consumed_mark on public.consumed
  for insert to authenticated with check (true);
