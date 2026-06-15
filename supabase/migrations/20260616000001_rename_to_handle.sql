-- 1. profiles.display_name → profiles.handle
alter table public.profiles rename column display_name to handle;
do $$ begin
  execute 'alter table test.profiles rename column display_name to handle';
exception when undefined_table then null; end $$;

-- Partial unique index: nulls allowed (handle set lazily in Python on first profile access)
create unique index profiles_handle_unique on public.profiles (handle)
  where handle is not null;

-- Reset handles that were set to email (invalid as URL handle)
update public.profiles set handle = null where handle like '%@%';
do $$ begin
  execute 'update test.profiles set handle = null where handle like ''%@%''';
exception when undefined_table then null; end $$;

-- Update trigger: insert with handle = null (Python sets it on first access)
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (auth_user_id, email, handle)
    values (new.id, new.email, null) on conflict do nothing;
  begin
    insert into test.profiles (auth_user_id, email, handle)
      values (new.id, new.email, null) on conflict do nothing;
  exception when undefined_table then null;
  end;
  return new;
end;
$$;

-- 2. organizations.slug → organizations.handle
alter table public.organizations rename column slug to handle;
do $$ begin
  execute 'alter table test.organizations rename column slug to handle';
exception when undefined_table then null; end $$;

drop index if exists organizations_slug_unique;
create unique index organizations_handle_unique on public.organizations (handle);
