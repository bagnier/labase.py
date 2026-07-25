-- emit() now records the business event INSIDE the request's own transaction, so the fact commits
-- iff the action commits (atomic) — replacing the former detached, best-effort persister. Two
-- consequences captured here:
--
--   1. `dispatched_at` — a cursor the async event tailer (next brick) uses to claim facts it has
--      not yet fanned out to consumers, straight off this one table (no separate event log).
--   2. INSERT grant — the authenticated role must write its OWN-attributed rows on the request
--      session. A member may only insert events where user_id = auth.uid(); admin writes (auth
--      signals, server actions, the tailer) go through the BYPASSRLS session and skip the check.
--      Self-attributed forgery via PostgREST is accepted for now (to harden later).

alter table public.business_events add column dispatched_at timestamptz;

-- The tailer claims facts not yet dispatched, oldest first.
create index business_events_undispatched_idx on public.business_events (id)
  where dispatched_at is null;

grant insert on public.business_events to authenticated;

-- id is a uuid7 (default public.uuidv7(), execute granted in 20260703000000) — no sequence to grant;
-- a self-attributed PostgREST insert gets its id from the column default.

create policy "business_events: self-attributed insert"
  on public.business_events for insert to authenticated
  with check (user_id = auth.uid());
