create schema if not exists test;

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
