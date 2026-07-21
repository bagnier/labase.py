-- Last-owner invariant, enforced in the database.
--
-- `ensure_not_last_owner` (domain service) is the only guard the in-app routes pass
-- through, but the RLS policies (`owner delete`, `self leave`, `owner update`) carry no
-- last-owner condition and `authenticated` holds direct DELETE/UPDATE — so a raw
-- PostgREST / supabase-js client wielding the JWT could delete or demote the final owner
-- and orphan the org. This trigger closes that gap (and the TOCTOU race the Python check
-- can't cover) by rejecting any DELETE/UPDATE that would leave an org ownerless.
--
-- Cascades must still pass: deleting an org (cascade → memberships) or an auth user
-- (cascade → their memberships) fires this BEFORE trigger with the parent row already
-- gone from the transaction's snapshot, so we skip the guard when either parent is absent.
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
    -- A parent being deleted cascades here with its row already gone from the snapshot
    -- (org delete → memberships, user delete → memberships); let those through.
    if exists (select 1 from public.organizations where id = old.org_id)
       and exists (select 1 from auth.users where id = old.auth_user_id)
       and not exists (
         select 1 from public.memberships
         where org_id = old.org_id
           and role = 'owner'
           and auth_user_id <> old.auth_user_id
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
