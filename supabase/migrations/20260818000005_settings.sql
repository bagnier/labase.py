-- Admin-tunable app settings: a server-wide value per (app, key), optionally overridden per org.
--
-- Seeded from each app's declared values, edited from the console.

create table public.app_settings (
  app_name   text        not null,
  key        text        not null,
  value      text        not null,  -- stored as text; coerced by the app's declared SettingDef
  version    integer     not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (app_name, key)
);

create trigger app_settings_updated_at
  before update on public.app_settings
  for each row execute procedure public.set_updated_at();

-- Admin session only: RLS on with no policy.
alter table public.app_settings enable row level security;

grant select, insert, update, delete on public.app_settings to service_role;


-- ── Per-organization overrides ──────────────────────────────────────────────────────────────
-- The console writes; members read their org's rows, so the RLS session resolves them.

create table public.org_app_settings (
  app_name   text        not null,
  key        text        not null,
  org_id     uuid        not null references public.organizations(id) on delete cascade,
  value      text        not null,
  version    integer     not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (app_name, key, org_id)
);

create trigger org_app_settings_updated_at
  before update on public.org_app_settings
  for each row execute procedure public.set_updated_at();

alter table public.org_app_settings enable row level security;

create policy "org_app_settings: member read"
  on public.org_app_settings for select
  using (org_id in (select public.user_org_ids()));

grant select on public.org_app_settings to authenticated;
grant select, insert, update, delete on public.org_app_settings to service_role;
