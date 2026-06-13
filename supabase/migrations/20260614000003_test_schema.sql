create schema if not exists test;

-- Redefine to also insert into test.profiles (already referenced in handle_new_user body above,
-- but we need test schema to actually exist before the exception-silencing works correctly)
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (auth_user_id, email)
    values (new.id, new.email) on conflict do nothing;
  begin
    insert into test.profiles (auth_user_id, email)
      values (new.id, new.email) on conflict do nothing;
  exception when undefined_table then null;
  end;
  return new;
end;
$$;

grant usage on schema test to authenticated;
grant select, insert, update, delete on all tables in schema test to authenticated;
alter default privileges in schema test grant select, insert, update, delete on tables to authenticated;
