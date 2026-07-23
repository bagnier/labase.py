-- Make every app→auth.users foreign key DEFERRABLE (kept INITIALLY IMMEDIATE).
--
-- Why: an app FK to auth.users takes a FOR KEY SHARE lock on the referenced auth.users row at
-- INSERT time, held until the writing transaction ends. In production this is harmless — the worker
-- that seeds a new account commits in milliseconds and frees the lock. But the API test driver runs
-- a whole scenario inside ONE transaction that is rolled back at the end: every seeded row
-- (membership, profile, todo, page, …) then holds that lock for the entire test. When the same test
-- asks GoTrue — a separate service, on its own connection — to delete or mutate that user, GoTrue's
-- write to auth.users blocks on the never-committing test transaction, and since it all shares one
-- event loop, it self-deadlocks.
--
-- INITIALLY IMMEDIATE keeps production behaviour byte-for-byte identical (the check, and its lock,
-- still fire at INSERT). Marking the constraints DEFERRABLE only grants the *capability* to defer:
-- the API test driver issues `SET CONSTRAINTS ALL DEFERRED` at the start of its rolled-back
-- transaction, so these checks (and their auth.users locks) move to a commit that never happens —
-- no lock, no deadlock. App-internal FKs stay NOT DEFERRABLE, so tests still catch their violations
-- immediately. Only tables an *external* service (GoTrue/auth.users) mutates concurrently need this.

ALTER TABLE public.api_keys
  ALTER CONSTRAINT api_keys_created_by_fkey DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.calendar_events
  ALTER CONSTRAINT calendar_events_user_id_fkey DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.card_states
  ALTER CONSTRAINT card_states_user_id_fkey DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.deck_subscriptions
  ALTER CONSTRAINT deck_subscriptions_user_id_fkey DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.memberships
  ALTER CONSTRAINT memberships_auth_user_id_fkey DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.org_files
  ALTER CONSTRAINT org_files_user_id_fkey DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.pages
  ALTER CONSTRAINT pages_user_id_fkey DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.profiles
  ALTER CONSTRAINT profiles_auth_user_id_fkey DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE public.todos
  ALTER CONSTRAINT todos_user_id_fkey DEFERRABLE INITIALLY IMMEDIATE;
