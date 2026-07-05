-- Per-organisation API keys: the machine face of the JSON API.
-- The secret is shown once and stored hashed (sha256); requests authenticate
-- with `Authorization: Bearer lbk_...` and run under the creator's RLS context,
-- pinned to the key's organisation at the HTTP layer.
create table public.api_keys (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null references public.organizations(id) on delete cascade,
  created_by   uuid not null references auth.users(id) on delete cascade,
  name         text not null,
  prefix       text not null,          -- displayable head of the token
  key_hash     text not null unique,   -- sha256 hex of the full token
  last_used_at timestamptz,
  revoked_at   timestamptz,
  version      integer not null default 1,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create trigger api_keys_updated_at
  before update on public.api_keys
  for each row execute procedure public.set_updated_at();

alter table public.api_keys enable row level security;

-- Owner-managed: members neither see nor manage keys. Token resolution happens
-- on the admin connection (no JWT exists yet at that point — explicit check).
create policy "api_keys: org owners"
  on public.api_keys for all
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

grant select, insert, update, delete on public.api_keys to authenticated;
grant select, insert, update, delete on public.api_keys to service_role;
