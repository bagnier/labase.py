-- Occurrences folded into issues by stack fingerprint. Admin only: RLS on with no policy.

create type public.issue_status as enum ('new', 'unresolved', 'resolved', 'ignored', 'regressed');

create table public.issues (
  id                  uuid                primary key default public.uuidv7(),
  fingerprint         text                not null unique,
  title               text                not null,
  status              public.issue_status not null default 'new',
  occurrence_count    bigint              not null default 0,
  first_seen          timestamptz         not null default now(),
  last_seen           timestamptz         not null default now(),
  -- A sighting past the resolved release is a regression. `version` is the optimistic lock.
  first_release       text                not null default 'dev',
  last_release        text                not null default 'dev',
  resolved_in_release text,
  version             integer             not null default 1,
  created_at          timestamptz         not null default now(),
  updated_at          timestamptz         not null default now()
);

create index issues_last_seen_idx on public.issues (last_seen desc);

create trigger issues_updated_at
  before update on public.issues
  for each row execute procedure public.set_updated_at();

alter table public.issues enable row level security;

grant select, insert, update, delete on public.issues to service_role;


create table public.issue_occurrences (
  id         uuid        primary key default public.uuidv7(),
  issue_id   uuid        not null references public.issues(id) on delete cascade,
  created_at timestamptz not null default now(),
  -- stack, request, user, org, request_id: the link to its log lines.
  context    jsonb       not null default '{}'
);

-- Newest-first per issue.
create index issue_occurrences_issue_idx on public.issue_occurrences (issue_id, id desc);

alter table public.issue_occurrences enable row level security;

grant select, insert, update, delete on public.issue_occurrences to service_role;
