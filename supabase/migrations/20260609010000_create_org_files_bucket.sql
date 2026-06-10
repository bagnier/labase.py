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

create policy "org-files: org members delete"
  on storage.objects for delete
  using (
    bucket_id = 'org-files'
    and (storage.foldername(name))[1]::uuid in (select public.user_orgs())
  );
