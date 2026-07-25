create table public.audit_logs (
  id         uuid        primary key default public.uuidv7(),
  created_at timestamptz not null default now(),
  level      text        not null,
  event      text        not null,
  user_id    uuid,
  ip         text,
  payload    jsonb
);

-- append-only via service_role — no GRANT to authenticated intentional
alter table public.audit_logs enable row level security;

create index audit_logs_created_at_idx on public.audit_logs (created_at desc);
create index audit_logs_event_idx      on public.audit_logs (event);
create index audit_logs_user_id_idx    on public.audit_logs (user_id) where user_id is not null;
