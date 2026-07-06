-- Email change: profiles.email mirrors auth.users.email. A trigger covers every
-- change path (app flow, Studio, support scripts) — no app-side sync to forget.
-- Same dual-schema tolerance as handle_new_user (test schema may be absent).
create or replace function public.sync_profile_email()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  update public.profiles set email = new.email where auth_user_id = new.id;
  begin
    update test.profiles set email = new.email where auth_user_id = new.id;
  exception when undefined_table then null;
  end;
  return new;
end;
$$;

create trigger on_auth_user_email_changed
  after update of email on auth.users
  for each row
  when (old.email is distinct from new.email)
  execute procedure public.sync_profile_email();
