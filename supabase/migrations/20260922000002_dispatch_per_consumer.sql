-- A fact's delivery to its durable ``on`` consumers is tracked per consumer, not per record: the
-- single ``dispatched_at`` flag let whichever instance checked a fact first foreclose it for every
-- consumer, including one only *that instance's* wiring lacked (a rolling deploy; an app switched
-- on and not yet restarted everywhere). ``business_events.dispatched_at`` keeps its column but
-- narrows to what it is now: has this record been checked for a kind no class can rebuild — so it
-- is renamed to say that.
alter table public.business_events rename column dispatched_at to checked_at;
alter index public.business_events_undispatched_idx rename to business_events_checked_idx;

-- Each durable consumer (queue topic) claims its own backlog off its own cursor, the same
-- ``id > cursor`` shape ``scan_spread`` already reads off — a topic newly registered (an app
-- switched on, then restarted) starts at nil and so still finds every fact recorded before it
-- existed; one already caught up only re-reads what is newer than its own last claim.
create table public.event_dispatch_cursors (
  topic  text not null primary key,
  cursor uuid not null
);

alter table public.event_dispatch_cursors enable row level security;

-- The idempotency ledger a per-topic cursor needs: a cursor only advances past the *settled*
-- prefix (a late-committing lower id must not be skipped, see ``scan_spread``), so a fact still
-- above the settle window is retried, unchanged, on every tick until it is — this is what keeps a
-- retry from enqueuing the same consumer's task twice.
create table public.dispatched_consumers (
  event_id      uuid        not null,
  topic         text        not null,
  dispatched_at timestamptz not null default now(),
  primary key (event_id, topic)
);

alter table public.dispatched_consumers enable row level security;
