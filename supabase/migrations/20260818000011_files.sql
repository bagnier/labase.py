-- Org files: rows here, bytes in Supabase Storage under {org_id}/…, plus immutable share tokens
-- that let an anonymous visitor download one.

create table public.org_files (
  id             uuid        primary key default public.uuidv7(),
  org_id         uuid        not null references public.organizations(id) on delete cascade,
  uploaded_by    uuid        not null references auth.users(id) on delete cascade
                             deferrable initially immediate,
  -- The uploader's email as it read *then*, so the list survives RLS hiding a co-member's
  -- identity and an account being closed.
  uploader_email text        not null default '',
  filename       text        not null,
  storage_path   text        not null,
  content_type   text        not null default 'application/octet-stream',
  size_bytes     bigint      not null default 0,
  version        integer     not null default 1,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index org_files_org_created_at_idx on public.org_files (org_id, created_at desc);

create trigger org_files_updated_at
  before update on public.org_files
  for each row execute procedure public.set_updated_at();

alter table public.org_files enable row level security;

create policy "org_files: member all"
  on public.org_files for all
  using  (org_id in (select public.user_org_ids()))
  with check (org_id in (select public.user_org_ids()));

grant select, insert, update, delete on public.org_files to authenticated;
grant select, insert, update, delete on public.org_files to service_role;


-- Immutable, and the token *is* the auth gate — hence uuid4 (unguessable, no embedded timestamp),
-- no version, no updated_at, no RLS.
create table public.org_file_share_tokens (
  token      uuid        primary key default gen_random_uuid(),
  file_id    uuid        not null references public.org_files(id) on delete cascade,
  expires_at timestamptz not null
);

create index org_file_share_tokens_file_id_idx on public.org_file_share_tokens (file_id);

grant select, insert, update, delete on public.org_file_share_tokens to authenticated;
grant select, insert, update, delete on public.org_file_share_tokens to service_role;


-- ── Storage ─────────────────────────────────────────────────────────────────────────────────
-- The bucket and its policies live in `storage`, not `public`, so a schema clone cannot carry
-- them: scripts/provision_schema.py recreates this block per worktree, and
-- tests/test_provision_schema.py fails loudly if the two drift apart.

insert into storage.buckets (id, name, public, file_size_limit)
values ('org-files', 'org-files', false, 52428800)
on conflict (id) do nothing;

create policy "org-files: org members select"
  on storage.objects for select
  using (
    bucket_id = 'org-files'
    and (storage.foldername(name))[1]::uuid in (select public.user_org_ids())
  );

create policy "org-files: org members insert"
  on storage.objects for insert
  with check (
    bucket_id = 'org-files'
    and (storage.foldername(name))[1]::uuid in (select public.user_org_ids())
  );

create policy "org-files: org members update"
  on storage.objects for update
  using (
    bucket_id = 'org-files'
    and (storage.foldername(name))[1]::uuid in (select public.user_org_ids())
  );

create policy "org-files: org members delete"
  on storage.objects for delete
  using (
    bucket_id = 'org-files'
    and (storage.foldername(name))[1]::uuid in (select public.user_org_ids())
  );
