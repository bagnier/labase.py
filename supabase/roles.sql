-- Wipe auth users before migrations so every db-reset starts with a clean slate.
-- GoTrue (auth.users) is not touched by `supabase db reset` alone: old JWT tokens
-- would remain valid and old admins would prevent the first-registrant-becomes-admin
-- bootstrap. Running here (before migrations) limits CASCADE to auth.* tables only —
-- public schema tables don't exist yet, so no noisy NOTICE cascade.
-- Run `make db-seed` afterwards to create the dev user + org.
TRUNCATE auth.users CASCADE;
