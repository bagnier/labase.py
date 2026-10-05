-- `supabase db reset` keeps auth.users: their tokens would stay valid and an old admin would
-- block the first-sign-up-is-admin bootstrap. Before migrations, the CASCADE reaches auth.* only.
-- `make db-seed` then creates the dev user and org.
TRUNCATE auth.users CASCADE;
