-- Per-organisation overrides of app settings ("beta for this customer").
-- The console (service_role) writes; org members may read their own org's rows
-- so apps resolve org-scoped flags through the regular RLS session. Becomes
-- plan-tier gating for free once billing exists.
create table public.org_app_settings (
  app        text not null,
  key        text not null,
  org_id     uuid not null references public.organizations(id) on delete cascade,
  value      text not null,
  version    integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (app, key, org_id)
);

create trigger org_app_settings_updated_at
  before update on public.org_app_settings
  for each row execute procedure public.set_updated_at();

alter table public.org_app_settings enable row level security;

create policy "org_app_settings: org members read"
  on public.org_app_settings for select
  using (org_id in (select public.user_orgs()));

grant select on public.org_app_settings to authenticated;
grant select, insert, update, delete on public.org_app_settings to service_role;
