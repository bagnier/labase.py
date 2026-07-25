create type public.invitation_status as enum ('pending', 'accepted', 'revoked');

create table public.org_invitations (
  id         uuid primary key default public.uuidv7(),
  org_id     uuid not null references public.organizations(id) on delete cascade,
  email      text not null,
  role       public.org_role not null default 'member',
  token      uuid not null unique default gen_random_uuid(),
  -- nullable, no FK: invitation belongs to the org; inviter leaving doesn't invalidate it
  invited_by uuid,
  status     public.invitation_status not null default 'pending',
  version    integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger org_invitations_updated_at
  before update on public.org_invitations
  for each row execute procedure public.set_updated_at();

alter table public.org_invitations enable row level security;

create policy "org_invitations: member read"
  on public.org_invitations for select
  using (org_id in (select public.user_orgs()));

create policy "org_invitations: owner insert"
  on public.org_invitations for insert
  with check (public.user_is_org_owner(org_id));

create policy "org_invitations: owner update"
  on public.org_invitations for update
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

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

  insert into public.memberships (org_id, auth_user_id, role)
  values (v_inv.org_id, auth.uid(), v_inv.role)
  on conflict (org_id, auth_user_id) do nothing;

  update public.org_invitations set status = 'accepted' where id = v_inv.id;
end;
$$;

grant select, insert, update, delete on public.org_invitations to authenticated;
grant select, insert, update, delete on public.org_invitations to service_role;
