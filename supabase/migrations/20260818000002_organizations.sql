-- Organizations, memberships, invitations, and the RLS helpers `user_org_ids()` and
-- `user_is_org_owner()`: a table is org-scoped iff its policies call them.

create type public.org_role as enum ('owner', 'member');
create type public.invitation_status as enum ('pending', 'accepted', 'revoked');


-- ── organizations ───────────────────────────────────────────────────────────────────────────

create table public.organizations (
  id         uuid        primary key default public.uuidv7(),
  name       text        not null,
  handle     text        not null default '' unique,
  -- IANA zone the org's dates are entered and shown in.
  timezone   text        not null default 'UTC',
  version    integer     not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger organizations_updated_at
  before update on public.organizations
  for each row execute procedure public.set_updated_at();

alter table public.organizations enable row level security;


-- ── memberships ─────────────────────────────────────────────────────────────────────────────
-- The FK to auth.users is DEFERRABLE (INITIALLY IMMEDIATE): its FOR KEY SHARE lock, held by the
-- API test driver's one open transaction, would block GoTrue mutating the user; the driver
-- defers it. App-internal FKs stay NOT DEFERRABLE.

create table public.memberships (
  org_id     uuid            not null references public.organizations(id) on delete cascade,
  user_id    uuid            not null references auth.users(id) on delete cascade
                             deferrable initially immediate,
  role       public.org_role not null default 'member',
  version    integer         not null default 1,
  created_at timestamptz     not null default now(),
  updated_at timestamptz     not null default now(),
  primary key (org_id, user_id)
);

create index memberships_user_id_idx on public.memberships (user_id);

create trigger memberships_updated_at
  before update on public.memberships
  for each row execute procedure public.set_updated_at();

alter table public.memberships enable row level security;


-- ── The RLS vocabulary ──────────────────────────────────────────────────────────────────────

create or replace function public.user_org_ids()
returns setof uuid language sql stable security definer set search_path = '' as $$
  select org_id from public.memberships where user_id = auth.uid()
$$;

create or replace function public.user_is_org_owner(p_org_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists(
    select 1 from public.memberships
    where org_id = p_org_id
      and user_id = auth.uid()
      and role = 'owner'
  )
$$;

-- Policies run as the caller, so the caller needs EXECUTE on the helpers they call.
grant execute on function public.user_org_ids() to authenticated;
grant execute on function public.user_is_org_owner(uuid) to authenticated;


-- ── Policies ────────────────────────────────────────────────────────────────────────────────

create policy "organizations: member read"
  on public.organizations for select
  using (id in (select public.user_org_ids()));

create policy "organizations: owner update"
  on public.organizations for update
  using (public.user_is_org_owner(id))
  with check (public.user_is_org_owner(id));

create policy "memberships: member read"
  on public.memberships for select
  using (org_id in (select public.user_org_ids()));

-- Only an owner adds a member. The first owner comes with the org, from
-- `create_org_with_owner`: a policy cannot tell a new org from an existing one.
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

create policy "memberships: self leave"
  on public.memberships for delete
  using (user_id = auth.uid());

grant select, update on public.organizations to authenticated;
grant select, insert, update, delete on public.memberships   to authenticated;


-- ── Creating an org ─────────────────────────────────────────────────────────────────────────
-- The only way an org comes to exist, never ownerless. An API role may only seat itself; the
-- admin session seats whoever it names (`role`, as `current_user` is the owner here). Id and
-- stamp come from the app's key shape and clock.
create or replace function public.create_org_with_owner(
  p_id uuid,
  p_name text,
  p_handle text,
  p_owner uuid,
  p_at timestamptz
) returns void
  language plpgsql
  security definer
  set search_path = ''
as $$
begin
  if current_setting('role') <> 'none' and p_owner is distinct from auth.uid() then
    raise exception 'an org is created for its creator' using errcode = '42501';
  end if;
  insert into public.organizations (id, name, handle, created_at, updated_at)
    values (p_id, p_name, p_handle, p_at, p_at);
  insert into public.memberships (org_id, user_id, role, created_at, updated_at)
    values (p_id, p_owner, 'owner', p_at, p_at);
end;
$$;

grant execute on function public.create_org_with_owner(uuid, text, text, uuid, timestamptz)
  to authenticated;
grant select, insert, update, delete on public.organizations to service_role;
grant select, insert, update, delete on public.memberships   to service_role;


-- ── The last-owner invariant, enforced in the database ──────────────────────────────────────
--
-- `authenticated` holds DELETE/UPDATE, so a PostgREST client could orphan an org; the trigger
-- also closes the race the Python check leaves. Skipped when the org or user is gone (cascade).
create or replace function public.prevent_last_owner_removal()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  -- Only RAISE: an early `return OLD` from a BEFORE UPDATE would discard a legitimate update.
  if old.role = 'owner' and not (tg_op = 'UPDATE' and new.role = 'owner') then
    if exists (select 1 from public.organizations where id = old.org_id)
       and exists (select 1 from auth.users where id = old.user_id)
       and not exists (
         select 1 from public.memberships
         where org_id = old.org_id
           and role = 'owner'
           and user_id <> old.user_id
       ) then
      raise exception 'cannot remove or demote the last owner of an organization'
        using errcode = 'check_violation';
    end if;
  end if;

  if tg_op = 'DELETE' then
    return old;
  end if;
  return new;
end;
$$;

create trigger memberships_prevent_last_owner_removal
  before delete or update on public.memberships
  for each row execute procedure public.prevent_last_owner_removal();


-- ── org_invitations ─────────────────────────────────────────────────────────────────────────

create table public.org_invitations (
  id         uuid                     primary key default public.uuidv7(),
  org_id     uuid                     not null references public.organizations(id) on delete cascade,
  email      text                     not null,
  role       public.org_role          not null default 'member',
  token      uuid                     not null unique default gen_random_uuid(),
  -- No FK: the invitation belongs to the org, so an inviter leaving must not invalidate it.
  invited_by uuid                     not null,
  status     public.invitation_status not null default 'pending',
  version    integer                  not null default 1,
  created_at timestamptz              not null default now(),
  updated_at timestamptz              not null default now()
);

create trigger org_invitations_updated_at
  before update on public.org_invitations
  for each row execute procedure public.set_updated_at();

alter table public.org_invitations enable row level security;

-- A pending invitation carries the token that accepts it: only an owner reads one.
create policy "org_invitations: owner read"
  on public.org_invitations for select
  using (public.user_is_org_owner(org_id));

create policy "org_invitations: owner insert"
  on public.org_invitations for insert
  with check (public.user_is_org_owner(org_id));

create policy "org_invitations: owner update"
  on public.org_invitations for update
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

-- An invitee is not yet a member, so RLS cannot show them their own invitation: both functions
-- run as owner and answer on the token alone.
create or replace function public.get_invitation_by_token(p_token uuid)
returns setof public.org_invitations
language sql stable security definer set search_path = '' as $$
  select * from public.org_invitations where token = p_token limit 1;
$$;

create or replace function public.accept_org_invitation(p_token uuid)
returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_inv public.org_invitations;
  v_caller_email text;
begin
  select * into v_inv from public.org_invitations where token = p_token for update;

  if not found then
    raise exception 'invitation not found or already used' using errcode = 'P0404';
  end if;

  if v_inv.status = 'accepted' then
    return;
  end if;

  if v_inv.status != 'pending' then
    raise exception 'invitation not found or already used' using errcode = 'P0404';
  end if;

  select email into v_caller_email
  from auth.users where id = auth.uid();

  if lower(v_caller_email) != lower(v_inv.email) then
    raise exception 'invitation not found or already used' using errcode = 'P0404';
  end if;

  insert into public.memberships (org_id, user_id, role)
  values (v_inv.org_id, auth.uid(), v_inv.role)
  on conflict (org_id, user_id) do nothing;

  update public.org_invitations set status = 'accepted' where id = v_inv.id;
end;
$$;

-- The invitee accepts on their own session. The lookup is the app's alone: the token is the
-- credential, so whoever holds it reads its invitation — before being a member of anything.
grant execute on function public.accept_org_invitation(uuid) to authenticated;
revoke all on function public.get_invitation_by_token(uuid) from public;
grant execute on function public.get_invitation_by_token(uuid) to app_rls;

grant select, insert, update, delete on public.org_invitations to authenticated;
grant select, insert, update, delete on public.org_invitations to service_role;
