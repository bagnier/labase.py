-- Replace accept_org_invitation to use a stable custom SQLSTATE (P0404)
-- instead of the generic P0001, so callers can match by code rather than message text.
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
    -- Idempotent: already accepted, do nothing (caller redirects to dashboard)
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

  insert into public.memberships (org_id, auth_user_id, role)
  values (v_inv.org_id, auth.uid(), v_inv.role)
  on conflict (org_id, auth_user_id) do nothing;

  update public.org_invitations set status = 'accepted' where id = v_inv.id;
end;
$$;
