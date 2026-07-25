create table public.org_files (
  id             uuid primary key default public.uuidv7(),
  org_id         uuid not null references public.organizations(id) on delete cascade,
  user_id        uuid not null references auth.users(id) on delete cascade,
  filename       text not null,
  storage_path   text not null,
  content_type   text not null default 'application/octet-stream',
  size_bytes     bigint not null default 0,
  uploader_email text not null default '',
  version        integer not null default 1,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create trigger org_files_updated_at
  before update on public.org_files
  for each row execute procedure public.set_updated_at();

create index org_files_org on public.org_files (org_id, created_at desc);

alter table public.org_files enable row level security;

create policy "org_files: org members"
  on public.org_files for all
  using  (org_id in (select public.user_orgs()))
  with check (org_id in (select public.user_orgs()));

grant select, insert, update, delete on public.org_files to authenticated;
grant select, insert, update, delete on public.org_files to service_role;

-- Share tokens: immutable, token is the auth gate — no version, no updated_at, no RLS
create table public.org_file_share_tokens (
  token      uuid primary key default gen_random_uuid(),
  file_id    uuid not null references public.org_files(id) on delete cascade,
  expires_at timestamptz not null
);

create index org_file_share_tokens_file on public.org_file_share_tokens (file_id);

grant select, insert, update, delete on public.org_file_share_tokens to authenticated;
grant select, insert, update, delete on public.org_file_share_tokens to service_role;

-- Storage bucket
insert into storage.buckets (id, name, public, file_size_limit)
values ('org-files', 'org-files', false, 52428800)
on conflict (id) do nothing;

create policy "org-files: org members select"
  on storage.objects for select
  using (
    bucket_id = 'org-files'
    and (storage.foldername(name))[1]::uuid in (select public.user_orgs())
  );

create policy "org-files: org members insert"
  on storage.objects for insert
  with check (
    bucket_id = 'org-files'
    and (storage.foldername(name))[1]::uuid in (select public.user_orgs())
  );

create policy "org-files: org members update"
  on storage.objects for update
  using (
    bucket_id = 'org-files'
    and (storage.foldername(name))[1]::uuid in (select public.user_orgs())
  );

create policy "org-files: org members delete"
  on storage.objects for delete
  using (
    bucket_id = 'org-files'
    and (storage.foldername(name))[1]::uuid in (select public.user_orgs())
  );
