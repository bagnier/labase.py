-- Avatars share the org-files bucket under `avatars/`, a first segment the policies' uuid cast
-- would raise on. The helper guards the cast with a CASE (an AND may be reordered), so a non-org
-- segment reads as no org.

create or replace function public.storage_path_org_id(path text)
returns uuid
language sql
immutable
as $$
  select case
    when (storage.foldername(path))[1] ~
      '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    then (storage.foldername(path))[1]::uuid
  end
$$;

grant execute on function public.storage_path_org_id(text) to authenticated;

drop policy "org-files: org members select" on storage.objects;
create policy "org-files: org members select"
  on storage.objects for select
  using (
    bucket_id = 'org-files'
    and public.storage_path_org_id(name) in (select public.user_org_ids())
  );

drop policy "org-files: org members insert" on storage.objects;
create policy "org-files: org members insert"
  on storage.objects for insert
  with check (
    bucket_id = 'org-files'
    and public.storage_path_org_id(name) in (select public.user_org_ids())
  );

drop policy "org-files: org members update" on storage.objects;
create policy "org-files: org members update"
  on storage.objects for update
  using (
    bucket_id = 'org-files'
    and public.storage_path_org_id(name) in (select public.user_org_ids())
  );

drop policy "org-files: org members delete" on storage.objects;
create policy "org-files: org members delete"
  on storage.objects for delete
  using (
    bucket_id = 'org-files'
    and public.storage_path_org_id(name) in (select public.user_org_ids())
  );
