create policy "org-files: org members update"
  on storage.objects for update
  using (
    bucket_id = 'org-files'
    and (storage.foldername(name))[1]::uuid in (select public.user_orgs())
  );
