-- A personal org was structurally indistinguishable from a team one, so `_create_org`'s
-- idempotency guard (#14) could only ask "does this user own *any* org" — which also matches a
-- team org that user created themselves through `POST /organizations` before the worker
-- delivered their `UserCreated`, and skipped seeding the personal org every account is promised
-- at sign-up (#71). `is_personal` gives the guard a real predicate to ask instead.

alter table public.organizations
  add column is_personal boolean not null default false;

-- Every account before this migration already got its personal org at sign-up — `_create_org`
-- (#14) always seeded it first, so it is the earliest org each user owns. Backfilling on that
-- rule is what lets the guard trust `is_personal` for an account that signed up before today:
-- without it, every pre-migration account would read as owning no personal org, and the next
-- redelivered `UserCreated` for one of them would seed a second one.
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

-- Table-wide UPDATE (granted to `authenticated` in the foundation migration) let every owner-
-- writable column share one grant because they all were owner-writable. `is_personal` breaks
-- that: it must be stamped once, by `create_org_with_owner` alone, never by a client holding the
-- JWT — so it is carved out with a column-level grant instead of joining the table-wide one.
-- `version` is included because SQLAlchemy's optimistic-lock write always sets it, on every
-- update, whichever column changed.
revoke update on public.organizations from authenticated;
grant update (name, handle, timezone, version) on public.organizations to authenticated;

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
