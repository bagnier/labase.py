-- Demo app — a richer org-scoped context: month grid, agenda view, datetime handling.
-- Delete this file with apps/calendar/ when real work starts.

create table public.calendar_events (
  id          uuid        primary key default public.uuidv7(),
  org_id      uuid        not null references public.organizations(id) on delete cascade,
  user_id     uuid        not null references auth.users(id) on delete cascade
                          deferrable initially immediate,
  title       text        not null,
  starts_at   timestamptz not null,
  ends_at     timestamptz not null,
  location    text        not null default '',
  description text        not null default '',
  version     integer     not null default 1,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint calendar_events_ends_after_starts_check check (ends_at > starts_at)
);

create index calendar_events_org_starts_at_idx on public.calendar_events (org_id, starts_at);

create trigger calendar_events_updated_at
  before update on public.calendar_events
  for each row execute procedure public.set_updated_at();

alter table public.calendar_events enable row level security;

-- Any member reads and writes: the calendar is collaborative, with no owner-only rule in v1.
create policy "calendar_events: member all"
  on public.calendar_events for all
  using  (org_id in (select public.user_org_ids()))
  with check (org_id in (select public.user_org_ids()));

grant select, insert, update, delete on public.calendar_events to authenticated;
grant select, insert, update, delete on public.calendar_events to service_role;
