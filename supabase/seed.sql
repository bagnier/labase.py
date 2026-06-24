-- Wipe auth users so every db-reset starts with a clean slate.
-- Migrations recreate the public schema; GoTrue (auth.users) is not touched
-- by `supabase db reset` alone, so old JWT tokens would remain valid and old
-- admin users would prevent the first-registrant-becomes-admin bootstrap.
-- This file runs automatically after migrations on every `supabase db reset`.
-- Run `make db-seed` afterwards to create the dev user + org.
TRUNCATE auth.users CASCADE;
