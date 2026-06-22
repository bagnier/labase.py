-- Console-owned per-app settings overrides. Unset keys fall back to the app's declared default.
-- Written and read only through the BYPASSRLS admin/service session (console is admin-gated at
-- the HTTP layer); never exposed to the authenticated role.
create table public.app_settings (
  app        text not null,
  key        text not null,
  value      text not null,
  version    integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (app, key)
);

create trigger app_settings_updated_at
  before update on public.app_settings
  for each row execute procedure public.set_updated_at();

alter table public.app_settings enable row level security;

grant select, insert, update, delete on public.app_settings to service_role;
