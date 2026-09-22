-- Avatars share the org-files bucket, under avatars/{user_id}.{ext} — a first path segment that
-- is never an org id. Every storage policy casts that segment to uuid to scope the row by org, so
-- once an avatar exists, any user-scoped query over the bucket that has to evaluate its row (not
-- only an exact-match listing) raises. A helper guards the cast with a CASE — never an AND, since
-- Postgres may reorder an AND's operands but always evaluates a CASE branch by branch — so a
-- non-org segment reads as "no org", excluding the row instead of raising.

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
