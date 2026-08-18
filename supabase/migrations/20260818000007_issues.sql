-- Error tracking (Sentry-as-Postgres): thousands of occurrences deduped into few issues by stack
-- fingerprint, each with a lifecycle.
--
-- Server-level admin data: no grants to `authenticated`, RLS on with no policy — the same posture
-- as app_settings.

create type public.issue_status as enum ('new', 'unresolved', 'resolved', 'ignored', 'regressed');

create table public.issues (
  id                  uuid                primary key default public.uuidv7(),
  fingerprint         text                not null unique,
  title               text                not null,
  status              public.issue_status not null default 'new',
  occurrence_count    bigint              not null default 0,
  first_seen          timestamptz         not null default now(),
  last_seen           timestamptz         not null default now(),
  -- The app release an issue was first and last seen in, and the one it was resolved in — a later
  -- sighting past that release is a regression. Named `release`, not `version`: `version` is the
  -- optimistic-lock counter every table in this schema carries, and one word cannot mean both.
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
  -- stack, request path/method, user, org, request_id — the request_id pivots each occurrence to
  -- its correlated firehose lines, a link SaaS trackers cannot offer.
  context    jsonb       not null default '{}'
);

-- id is a uuid7 (time-ordered), so (issue_id, id desc) stays a valid newest-first cursor index.
create index issue_occurrences_issue_idx on public.issue_occurrences (issue_id, id desc);

alter table public.issue_occurrences enable row level security;

grant select, insert, update, delete on public.issue_occurrences to service_role;
