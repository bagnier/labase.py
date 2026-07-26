-- Make three columns say what the code already guarantees — turning an assumption into a
-- constraint rather than turning a constraint into a comment.
--
-- Each of these was typed nullable in the ORM while no write path could produce a NULL. That is
-- the wrong direction of slack: a reader has to trace every writer to learn what the type should
-- have told them, and nothing stops a future writer (or a client) from making the NULL real.
--
-- business_events matters most: the table carries a `self-attributed insert` RLS policy, so an
-- authenticated client can insert a row straight through PostgREST, bypassing both the Python
-- writer and the signup trigger. Until now such a row could land without an icon or a payload and
-- reach the console timeline. Here the constraint is the enforcement, not a tidy-up.

-- ── business_events.icon ────────────────────────────────────────────────────────────────────
-- Every event class carries `icon` as a ClassVar defaulting to "circle", and the signup trigger
-- writes 'user-plus' explicitly; the default matches the base so a hand-inserted row still shows
-- something in the timeline instead of an empty cell.
update public.business_events set icon = 'circle' where icon is null;

alter table public.business_events
  alter column icon set default 'circle',
  alter column icon set not null;

-- ── business_events.payload ─────────────────────────────────────────────────────────────────
-- The writer used to collapse an empty payload to NULL (`payload or None`), so "this event has no
-- extra fields" and "we don't know" shared one representation — and every reader answered with a
-- defensive `or {}`. An empty object says the first thing and only the first thing.
update public.business_events set payload = '{}'::jsonb where payload is null;

alter table public.business_events
  alter column payload set default '{}'::jsonb,
  alter column payload set not null;

-- ── org_invitations.invited_by ──────────────────────────────────────────────────────────────
-- One writer only (OrgRepository.create_invitation), whose parameter has always been a required
-- uuid, fed from the acting owner. No NULL can have been written by this application: if this
-- statement fails, the row was hand-inserted and deserves a human decision rather than a silent
-- backfill — an invitation with no inviter has no defensible value to fill in.
alter table public.org_invitations
  alter column invited_by set not null;

-- ── pages.search_vector ─────────────────────────────────────────────────────────────────────
-- A stored generated column over `coalesce(title,'') || ' ' || coalesce(content,'')`: to_tsvector
-- of a coalesced string is an empty tsvector, never NULL. The column was declared nullable by
-- hand; the constraint just records what the expression already cannot violate.
alter table public.pages
  alter column search_vector set not null;
