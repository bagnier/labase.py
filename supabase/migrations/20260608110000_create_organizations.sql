create table public.organizations (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  created_at timestamptz not null default now()
);

create type public.org_role as enum ('owner', 'admin', 'member');

create table public.memberships (
  org_id       uuid not null references public.organizations(id) on delete cascade,
  auth_user_id uuid not null references auth.users(id) on delete cascade,
  role         public.org_role not null default 'member',
  created_at   timestamptz not null default now(),
  primary key (org_id, auth_user_id)
);

create index memberships_user on public.memberships (auth_user_id);

-- Helper stable pour les policies (évite la sous-requête répétée côté Postgres)
create or replace function public.user_orgs()
returns setof uuid language sql stable security definer as $$
  select org_id from public.memberships where auth_user_id = auth.uid()
$$;

-- RLS organizations
alter table public.organizations enable row level security;

create policy "organizations: member read"
  on public.organizations for select
  using (id in (select public.user_orgs()));

create policy "organizations: owner update"
  on public.organizations for update
  using (id in (
    select org_id from public.memberships
    where auth_user_id = auth.uid() and role in ('owner', 'admin')
  ));

-- RLS memberships
alter table public.memberships enable row level security;

create policy "memberships: member read"
  on public.memberships for select
  using (org_id in (select public.user_orgs()));

create policy "memberships: owner manage"
  on public.memberships for all
  using (
    org_id in (
      select org_id from public.memberships
      where auth_user_id = auth.uid() and role in ('owner', 'admin')
    )
  )
  with check (
    org_id in (
      select org_id from public.memberships
      where auth_user_id = auth.uid() and role in ('owner', 'admin')
    )
  );

-- GRANTs rôle authenticated
grant select, insert, update, delete on public.organizations to authenticated;
grant select, insert, update, delete on public.memberships  to authenticated;

-- Schéma test
do $$
begin
  if exists (select 1 from information_schema.schemata where schema_name = 'test') then
    execute 'grant select, insert, update, delete on all tables in schema test to authenticated';
  end if;
end
$$;
