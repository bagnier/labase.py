-- Account deletion: GoTrue's soft delete obfuscates the email, which fired the
-- profiles sync trigger. That scramble must not propagate — and the deletion
-- flow removes the profiles row in the same open transaction, so the trigger's
-- UPDATE would block on it. Skip sync for soft-deleted users.
drop trigger on_auth_user_email_changed on auth.users;

create trigger on_auth_user_email_changed
  after update of email on auth.users
  for each row
  when (old.email is distinct from new.email and new.deleted_at is null)
  execute procedure public.sync_profile_email();
