create type public.org_role as enum ('owner', 'member');

create table public.organizations (
  id         uuid primary key default public.uuidv7(),
  name       text not null,
  handle     text not null default '',
  version    integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index organizations_handle_unique on public.organizations (handle);

create trigger organizations_updated_at
  before update on public.organizations
  for each row execute procedure public.set_updated_at();

create table public.memberships (
  org_id       uuid not null references public.organizations(id) on delete cascade,
  auth_user_id uuid not null references auth.users(id) on delete cascade,
  role         public.org_role not null default 'member',
  version      integer not null default 1,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  primary key (org_id, auth_user_id)
);

create index memberships_user on public.memberships (auth_user_id);

create trigger memberships_updated_at
  before update on public.memberships
  for each row execute procedure public.set_updated_at();

create or replace function public.user_orgs()
returns setof uuid language sql stable security definer as $$
  select org_id from public.memberships where auth_user_id = auth.uid()
$$;

create or replace function public.user_is_org_owner(check_org_id uuid)
returns boolean language sql stable security definer as $$
  select exists(
    select 1 from public.memberships
    where org_id = check_org_id
      and auth_user_id = auth.uid()
      and role = 'owner'
  )
$$;

alter table public.organizations enable row level security;

create policy "organizations: member read"
  on public.organizations for select
  using (id in (select public.user_orgs()));

-- Allow any authenticated user to create an organisation.
create policy "organizations: authenticated insert"
  on public.organizations for insert
  with check (true);

create policy "organizations: owner update"
  on public.organizations for update
  using (public.user_is_org_owner(id))
  with check (public.user_is_org_owner(id));

alter table public.memberships enable row level security;

create policy "memberships: member read"
  on public.memberships for select
  using (org_id in (select public.user_orgs()));

-- Also allows a user to insert themselves as owner of a new org (bootstrap: the
-- owner-only check alone creates a chicken-and-egg problem for the first membership).
create policy "memberships: owner insert"
  on public.memberships for insert
  with check (
    (auth_user_id = auth.uid() and role = 'owner')
    or public.user_is_org_owner(org_id)
  );

create policy "memberships: owner update"
  on public.memberships for update
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

create policy "memberships: owner delete"
  on public.memberships for delete
  using (public.user_is_org_owner(org_id));

create policy "memberships: self leave"
  on public.memberships for delete
  using (auth_user_id = auth.uid());

grant select, insert, update, delete on public.organizations to authenticated;
grant select, insert, update, delete on public.memberships  to authenticated;
grant select, insert, update, delete on public.organizations to service_role;
grant select, insert, update, delete on public.memberships  to service_role;

do $$
begin
  if exists (select 1 from information_schema.schemata where schema_name = 'test') then
    execute 'grant select, insert, update, delete on all tables in schema test to authenticated';
  end if;
end
$$;
