-- Per-organization API keys: the machine face of the JSON API.
--
-- The secret is shown once and stored hashed (sha256); requests authenticate with
-- `Authorization: Bearer lbk_...` and run under the creator's RLS context, pinned to the key's
-- organization at the HTTP layer.

create table public.api_keys (
  id           uuid        primary key default public.uuidv7(),
  org_id       uuid        not null references public.organizations(id) on delete cascade,
  created_by   uuid        not null references auth.users(id) on delete cascade
                           deferrable initially immediate,
  name         text        not null,
  prefix       text        not null,          -- displayable head of the token
  key_hash     text        not null unique,   -- sha256 hex of the full token
  last_used_at timestamptz,
  revoked_at   timestamptz,
  version      integer     not null default 1,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create trigger api_keys_updated_at
  before update on public.api_keys
  for each row execute procedure public.set_updated_at();

alter table public.api_keys enable row level security;

-- Owner-managed: members neither see nor manage keys. Resolving a bearer token happens on the
-- admin connection (no JWT exists yet at that point — the check there is explicit).
create policy "api_keys: owner all"
  on public.api_keys for all
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

grant select, insert, update, delete on public.api_keys to authenticated;
grant select, insert, update, delete on public.api_keys to service_role;


-- ── Resolving a bearer token ────────────────────────────────────────────────────────────────────
--
-- A key is resolved before any identity exists, so no policy can answer for it: this function
-- does, for a live key's hash and nothing else, on the app's own connection rather than a
-- BYPASSRLS one. It stamps `last_used_at` when older than `p_stale_before` (the app owns that
-- granularity). Executable by `app_rls` alone — PostgREST never resolves an `lbk_` token.

create function public.api_key_principal(
  p_key_hash text, p_now timestamptz, p_stale_before timestamptz
) returns table (created_by uuid, org_id uuid)
  language plpgsql volatile security definer set search_path = '' as $$
begin
  update public.api_keys k
     set last_used_at = p_now
   where k.key_hash = p_key_hash and k.revoked_at is null
     and (k.last_used_at is null or k.last_used_at < p_stale_before);
  return query
    select k.created_by, k.org_id from public.api_keys k
     where k.key_hash = p_key_hash and k.revoked_at is null;
end
$$;

revoke all on function public.api_key_principal(text, timestamptz, timestamptz) from public;
grant execute on function public.api_key_principal(text, timestamptz, timestamptz) to app_rls;
