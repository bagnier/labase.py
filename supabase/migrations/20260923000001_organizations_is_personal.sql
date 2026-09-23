-- A personal org was structurally indistinguishable from a team one, so `_create_org`'s
-- idempotency guard (#14) could only ask "does this user own *any* org" — which also matches a
-- team org that user created themselves through `POST /organizations` before the worker
-- delivered their `UserCreated`, and skipped seeding the personal org every account is promised
-- at sign-up (#71). `is_personal` gives the guard a real predicate to ask instead.

alter table public.organizations
  add column is_personal boolean not null default false;

-- `create or replace` cannot add a parameter in place — Postgres would keep the old 5-arg
-- overload and pick between it and this one by the defaults, ambiguously. Drop it first.
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
