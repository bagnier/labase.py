-- Evolve the audit_logs trail into the unified business-events store. Same row shape
-- (kind + user/org + ip/request_id + level + payload), but the producer becomes the typed
-- event bus (apps/shared/events.py) and the store becomes member-readable: RLS scopes rows to
-- the reader, so the profile and org-dashboard timelines read it on the user's OWN session
-- (no admin bypass, no Python-side filtering — the database enforces isolation).
alter table public.audit_logs rename to business_events;
alter table public.business_events rename column event to kind;

-- The emitting app OWNS its phosphor icon and carries it on the event, so the timeline renders
-- without shared having to map app→icon (a foundation must not name features). Nullable: rows
-- from the legacy audit() writer carry none and fall back to a generic glyph at render.
alter table public.business_events add column icon text;

-- Carry the indexes over under matching names.
alter index public.audit_logs_created_at_idx rename to business_events_created_at_idx;
alter index public.audit_logs_event_idx      rename to business_events_kind_idx;
alter index public.audit_logs_user_id_idx    rename to business_events_user_id_idx;
alter index public.audit_logs_org_id_idx     rename to business_events_org_id_idx;
alter index public.audit_logs_request_id_idx rename to business_events_request_id_idx;

-- Newest-first feeds by actor (profile) and by org (dashboard) — both order by id desc.
create index business_events_user_feed_idx
  on public.business_events (user_id, id desc) where user_id is not null;
create index business_events_org_feed_idx
  on public.business_events (org_id, id desc) where org_id is not null;

-- A member READS their own actions and every event of any org they belong to; admin keeps
-- full access via the BYPASSRLS service_role session. No insert/update/delete grant to
-- authenticated — the trail stays append-only, written only by the persister's admin session.
create policy "business_events: self or org member reads"
  on public.business_events for select
  using (user_id = auth.uid() or org_id in (select public.user_orgs()));

grant select on public.business_events to authenticated;
