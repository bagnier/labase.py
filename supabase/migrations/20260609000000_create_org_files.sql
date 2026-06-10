create table public.org_files (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null references public.organizations(id) on delete cascade,
  user_id      uuid not null references auth.users(id) on delete cascade,
  filename     text not null,
  storage_path text not null,
  content_type text not null default 'application/octet-stream',
  size_bytes   bigint not null default 0,
  created_at   timestamptz not null default now()
);

create index org_files_org on public.org_files (org_id, created_at desc);

alter table public.org_files enable row level security;

create policy "org_files: org members"
  on public.org_files for all
  using  (org_id in (select public.user_orgs()))
  with check (org_id in (select public.user_orgs()));

grant select, insert, update, delete on public.org_files to authenticated;
