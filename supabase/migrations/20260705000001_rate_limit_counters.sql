-- Shared fixed-window rate-limit counters (first Postgres-as-Redis brick).
-- Written only through the admin connection: no grants, RLS enabled with no
-- policies (deny-all for API roles) — same posture as audit_logs.
create table public.rate_limit_counters (
  key          text        not null,
  window_start timestamptz not null,
  count        integer     not null default 1,
  primary key (key, window_start)
);

alter table public.rate_limit_counters enable row level security;
