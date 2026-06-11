-- Remove the 'admin' org role: owner and member are the only roles going forward.

-- Update any existing admin memberships to owner before altering the enum.
update public.memberships set role = 'owner' where role = 'admin';

-- Drop policies that reference the role column before changing the enum type.
drop policy if exists "memberships: owner insert" on public.memberships;
drop policy if exists "memberships: owner update" on public.memberships;
drop policy if exists "memberships: owner delete" on public.memberships;
drop policy if exists "organizations: owner update" on public.organizations;

-- Rename the old helper function before dropping (policies may reference it).
drop function if exists public.user_is_org_admin(uuid);

-- Recreate the enum without 'admin'.
alter type public.org_role rename to org_role_old;
create type public.org_role as enum ('owner', 'member');
alter table public.memberships alter column role drop default;
alter table public.memberships
  alter column role type public.org_role using role::text::public.org_role;
alter table public.memberships alter column role set default 'member'::public.org_role;
drop type public.org_role_old;

-- Create the new helper function.
create or replace function public.user_is_org_owner(check_org_id uuid)
returns boolean language sql stable security definer as $$
  select exists(
    select 1 from public.memberships
    where org_id = check_org_id
      and auth_user_id = auth.uid()
      and role = 'owner'
  )
$$;

-- Recreate policies using the new function.
create policy "memberships: owner insert"
  on public.memberships for insert
  with check (public.user_is_org_owner(org_id));

create policy "memberships: owner update"
  on public.memberships for update
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

create policy "memberships: owner delete"
  on public.memberships for delete
  using (public.user_is_org_owner(org_id));

-- Update the organizations rename policy to use the new function.
create policy "organizations: owner update"
  on public.organizations for update
  using (public.user_is_org_owner(id));
