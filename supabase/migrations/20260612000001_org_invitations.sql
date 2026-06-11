create type invitation_status as enum ('pending', 'accepted', 'revoked');

create table public.org_invitations (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null references public.organizations(id) on delete cascade,
  email        text not null,
  role         org_role not null default 'member',
  token        uuid not null unique default gen_random_uuid(),
  invited_by   uuid not null,
  status       invitation_status not null default 'pending',
  created_at   timestamptz not null default now()
);

alter table public.org_invitations enable row level security;

-- Members can read pending invitations for their org
create policy "org_invitations: member read"
  on public.org_invitations for select
  using (public.user_is_org_owner(org_id) or exists(
    select 1 from public.memberships
    where memberships.org_id = org_invitations.org_id
      and memberships.auth_user_id = auth.uid()
  ));

-- Owners can insert invitations
create policy "org_invitations: owner insert"
  on public.org_invitations for insert
  with check (public.user_is_org_owner(org_id));

-- Owners can update (revoke) invitations
create policy "org_invitations: owner update"
  on public.org_invitations for update
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

-- SECURITY DEFINER: resolve invitation by token (no membership required)
create or replace function public.get_invitation_by_token(p_token uuid)
returns setof public.org_invitations
language sql stable security definer as $$
  select * from public.org_invitations where token = p_token limit 1;
$$;

-- SECURITY DEFINER: accept invitation atomically
-- Inserts membership and marks invitation as accepted.
-- Checks that the invitation is pending and that the caller's email matches.
create or replace function public.accept_org_invitation(p_token uuid)
returns void
language plpgsql security definer as $$
declare
  v_inv public.org_invitations;
  v_caller_email text;
begin
  select * into v_inv from public.org_invitations where token = p_token for update;

  if not found then
    raise exception 'invitation not found or already used' using errcode = 'P0001';
  end if;

  if v_inv.status = 'accepted' then
    -- Idempotent: already accepted, do nothing (caller redirects to dashboard)
    return;
  end if;

  if v_inv.status != 'pending' then
    raise exception 'invitation not found or already used' using errcode = 'P0001';
  end if;

  select email into v_caller_email
  from auth.users where id = auth.uid();

  if lower(v_caller_email) != lower(v_inv.email) then
    raise exception 'invitation not found or already used' using errcode = 'P0001';
  end if;

  insert into public.memberships (org_id, auth_user_id, role)
  values (v_inv.org_id, auth.uid(), v_inv.role)
  on conflict (org_id, auth_user_id) do nothing;

  update public.org_invitations set status = 'accepted' where id = v_inv.id;
end;
$$;
