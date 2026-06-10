alter table public.org_files
    add column uploader_email text not null default '';

create table public.org_file_share_tokens (
    token      uuid primary key default gen_random_uuid(),
    file_id    uuid not null references public.org_files(id) on delete cascade,
    expires_at timestamptz not null
);

create index org_file_share_tokens_file on public.org_file_share_tokens (file_id);

-- Share tokens are resolved by the app via service role (public endpoint); no RLS needed.
-- The token itself is the auth gate.
