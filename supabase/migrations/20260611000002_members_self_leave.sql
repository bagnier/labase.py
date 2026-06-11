-- Allow any member to delete their own membership row (leave the org).
-- The last-owner guard is enforced at the application layer.
create policy "memberships: self leave"
  on public.memberships for delete
  using (auth_user_id = auth.uid());
