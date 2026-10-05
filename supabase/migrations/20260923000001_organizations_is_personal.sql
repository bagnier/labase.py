-- `_create_org`'s idempotency guard asks for the user's personal org, not any org they own: a
-- team org created before `UserCreated` was delivered skipped the personal one (#71).

alter table public.organizations
  add column is_personal boolean not null default false;

-- The earliest org each user owns is their personal one; without the backfill a redelivered
-- `UserCreated` would seed a second.
with first_owned as (
  select distinct on (m.user_id) m.org_id
    from public.memberships as m
    inner join public.organizations as o on m.org_id = o.id
   where m.role = 'owner'
   order by m.user_id, o.created_at
)
update public.organizations as o
   set is_personal = true
  from first_owned as f
 where o.id = f.org_id;

-- Column-level UPDATE: `is_personal` is stamped by `create_org_with_owner` alone. `version`, as
-- SQLAlchemy's optimistic lock writes it on every update.
revoke update on public.organizations from authenticated;
grant update (name, handle, timezone, version) on public.organizations to authenticated;

-- Dropped first: `create or replace` would keep the 5-arg overload beside this one, ambiguously.
drop function if exists public.create_org_with_owner(uuid, text, text, uuid, timestamptz);

create function public.create_org_with_owner(
  p_id uuid,
  p_name text,
  p_handle text,
  p_owner uuid,
  p_at timestamptz,
  p_is_personal boolean default false
) returns void
  language plpgsql
  security definer
  set search_path = ''
as $$
begin
  if current_setting('role') <> 'none' and p_owner is distinct from auth.uid() then
    raise exception 'an org is created for its creator' using errcode = '42501';
  end if;
  insert into public.organizations (id, name, handle, is_personal, created_at, updated_at)
    values (p_id, p_name, p_handle, p_is_personal, p_at, p_at);
  insert into public.memberships (org_id, user_id, role, created_at, updated_at)
    values (p_id, p_owner, 'owner', p_at, p_at);
end;
$$;

grant execute on function public.create_org_with_owner(uuid, text, text, uuid, timestamptz, boolean)
  to authenticated;
