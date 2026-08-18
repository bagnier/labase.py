-- Multi-tenancy: organizations, their memberships and their invitations — plus the two
-- SECURITY DEFINER helpers every other app's RLS policy is written against.
--
-- Comes right after the foundation because `user_org_ids()` and `user_is_org_owner()` are the
-- vocabulary of isolation in this schema: a table is org-scoped iff its policies call them.

create type public.org_role as enum ('owner', 'member');
create type public.invitation_status as enum ('pending', 'accepted', 'revoked');


-- ── organizations ───────────────────────────────────────────────────────────────────────────

create table public.organizations (
  id         uuid        primary key default public.uuidv7(),
  name       text        not null,
  handle     text        not null default '' unique,
  -- IANA zone an org's dates are entered and displayed in (the calendar reads form input in it
  -- and renders stored UTC instants back into it). UTC until an owner picks one.
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
-- `user_id` is an `auth.users` id, as it is on every table in this schema. The FK is DEFERRABLE
-- (kept INITIALLY IMMEDIATE, so production behaviour is unchanged): an FK to auth.users takes a
-- FOR KEY SHARE lock on the referenced row at INSERT, held until the writing transaction ends,
-- and the API test driver keeps ONE transaction open for a whole scenario. When that scenario
-- then asks GoTrue — another service, another connection, same event loop — to mutate the user,
-- GoTrue blocks on the never-committing test transaction and self-deadlocks. The driver issues
-- `SET CONSTRAINTS ALL DEFERRED` to move the check past a commit that never happens. Only tables
-- an *external* service mutates concurrently need this; app-internal FKs stay NOT DEFERRABLE so
-- tests still catch their violations immediately.

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
returns setof uuid language sql stable security definer as $$
  select org_id from public.memberships where user_id = auth.uid()
$$;

create or replace function public.user_is_org_owner(p_org_id uuid)
returns boolean language sql stable security definer as $$
  select exists(
    select 1 from public.memberships
    where org_id = p_org_id
      and user_id = auth.uid()
      and role = 'owner'
  )
$$;


-- ── Policies ────────────────────────────────────────────────────────────────────────────────

create policy "organizations: member read"
  on public.organizations for select
  using (id in (select public.user_org_ids()));

-- Any authenticated user may create an organization.
create policy "organizations: authenticated insert"
  on public.organizations for insert
  with check (true);

create policy "organizations: owner update"
  on public.organizations for update
  using (public.user_is_org_owner(id))
  with check (public.user_is_org_owner(id));

create policy "memberships: member read"
  on public.memberships for select
  using (org_id in (select public.user_org_ids()));

-- Also lets a user insert themselves as owner of a new org (bootstrap: an owner-only check alone
-- is a chicken-and-egg problem for the very first membership).
create policy "memberships: owner insert"
  on public.memberships for insert
  with check (
    (user_id = auth.uid() and role = 'owner')
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
  using (user_id = auth.uid());

grant select, insert, update, delete on public.organizations to authenticated;
grant select, insert, update, delete on public.memberships   to authenticated;
grant select, insert, update, delete on public.organizations to service_role;
grant select, insert, update, delete on public.memberships   to service_role;


-- ── The last-owner invariant, enforced in the database ──────────────────────────────────────
--
-- The domain service guards it on the in-app routes, but the policies above carry no last-owner
-- condition and `authenticated` holds direct DELETE/UPDATE — so a raw PostgREST client wielding
-- the JWT could delete or demote the final owner and orphan the org. This trigger closes that gap,
-- and the TOCTOU race the Python check cannot cover.
--
-- Cascades must still pass: deleting an org (cascade → memberships) or an auth user (cascade →
-- their memberships) fires this BEFORE trigger with the parent row already gone from the
-- transaction's snapshot, so the guard is skipped when either parent is absent.
create or replace function public.prevent_last_owner_removal()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  -- Guard only fires when an owner row loses its owner status (a demotion or a delete).
  -- NB: a BEFORE UPDATE trigger writes whatever row it returns — so we must never early
  -- return OLD on a legitimate update (that would silently discard it); we only ever RAISE
  -- to block, and otherwise fall through to the correct per-op return at the bottom.
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

create policy "org_invitations: member read"
  on public.org_invitations for select
  using (org_id in (select public.user_org_ids()));

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
language sql stable security definer as $$
  select * from public.org_invitations where token = p_token limit 1;
$$;

create or replace function public.accept_org_invitation(p_token uuid)
returns void
language plpgsql security definer as $$
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

grant select, insert, update, delete on public.org_invitations to authenticated;
grant select, insert, update, delete on public.org_invitations to service_role;
