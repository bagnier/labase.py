create table public.audit_logs (
  id         bigserial primary key,
  created_at timestamptz not null default now(),
  level      text        not null,
  event      text        not null,
  user_id    uuid,
  ip         text,
  payload    jsonb
);

-- Seul le rôle service (postgres / service_role) peut écrire ; les users ne lisent pas leurs propres logs.
alter table public.audit_logs enable row level security;

-- Index pour les requêtes courantes depuis le dashboard
create index audit_logs_created_at_idx on public.audit_logs (created_at desc);
create index audit_logs_event_idx      on public.audit_logs (event);
create index audit_logs_user_id_idx    on public.audit_logs (user_id) where user_id is not null;
