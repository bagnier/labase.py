-- A fact's delivery to its durable ``on`` consumers is tracked per consumer, not per record: the
-- single ``dispatched_at`` flag let whichever instance checked a fact first foreclose it for every
-- consumer, including one only *that instance's* wiring lacked (a rolling deploy; an app switched
-- on and not yet restarted everywhere). ``business_events.dispatched_at`` keeps its column but
-- narrows to what it is now: has this record been checked for a kind no class can rebuild — so it
-- is renamed to say that.
alter table public.business_events rename column dispatched_at to checked_at;
alter index public.business_events_undispatched_idx rename to business_events_checked_idx;

-- Each durable consumer (queue topic) claims its own backlog off its own cursor, the same
-- ``id > cursor`` shape ``facts_above_cursor`` already reads off — a topic newly registered (an
-- app switched on, then restarted) starts at nil and so still finds every fact recorded before it
-- existed; one already caught up only re-reads what is newer than its own last claim.
create table public.event_dispatch_cursors (
  topic  text not null primary key,
  cursor uuid not null
);

alter table public.event_dispatch_cursors enable row level security;

-- A topic already delivering before this migration is not "newly registered": seed its cursor to
-- the highest fact it has already consumed, so it does not replay its whole history the first time
-- it claims its own cursor. A topic with no row here — genuinely never seen, the case the fix is
-- for — still starts at nil and backfills, exactly as it must.
insert into public.event_dispatch_cursors (topic, cursor)
select distinct on (consumer) consumer as topic, event_id as cursor
from public.consumed_events
order by consumer asc, event_id desc;

-- The idempotency ledger a per-topic cursor needs: a cursor only advances past the *settled*
-- prefix (a late-committing lower id must not be skipped, see ``facts_above_cursor``), so a fact
-- still above the settle window is retried, unchanged, on every tick until it is — this is what
-- keeps a retry from enqueuing the same consumer's task twice.
create table public.dispatched_consumers (
  event_id      uuid        not null,
  topic         text        not null,
  dispatched_at timestamptz not null default now(),
  primary key (event_id, topic)
);

alter table public.dispatched_consumers enable row level security;
