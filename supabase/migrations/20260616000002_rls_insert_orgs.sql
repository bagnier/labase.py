-- Allow any authenticated user to create an organisation.
create policy "organizations: authenticated insert"
  on public.organizations for insert
  with check (true);

-- Bootstrap fix: the previous policy only allowed existing owners to add members,
-- creating a chicken-and-egg problem when inserting the first (owner) membership.
-- Now also allow a user to insert themselves as owner of a new org.
drop policy "memberships: owner insert" on public.memberships;

create policy "memberships: owner insert"
  on public.memberships for insert
  with check (
    (auth_user_id = auth.uid() and role = 'owner')
    or public.user_is_org_owner(org_id)
  );

-- Allow org owners to manage decks and cards (create/edit/delete org content).
-- The existing grant only covers select for authenticated; extend it.
grant insert, update, delete on public.decks, public.cards to authenticated;

create policy "decks: org owner write"
  on public.decks for all
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

create policy "cards: org owner write"
  on public.cards for all
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));
