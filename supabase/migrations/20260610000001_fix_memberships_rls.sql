-- Fix infinite recursion: replace direct self-referencing sub-query with a
-- security-definer function that bypasses RLS when checking admin status.

create or replace function public.user_is_org_admin(check_org_id uuid)
returns boolean language sql stable security definer as $$
  select exists(
    select 1 from public.memberships
    where org_id = check_org_id
      and auth_user_id = auth.uid()
      and role in ('owner', 'admin')
  )
$$;

drop policy if exists "memberships: owner manage" on public.memberships;

create policy "memberships: owner insert"
  on public.memberships for insert
  with check (public.user_is_org_admin(org_id));

create policy "memberships: owner update"
  on public.memberships for update
  using (public.user_is_org_admin(org_id))
  with check (public.user_is_org_admin(org_id));

create policy "memberships: owner delete"
  on public.memberships for delete
  using (public.user_is_org_admin(org_id));
