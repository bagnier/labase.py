-- Runs after migrations on `supabase db reset`; why auth.users is wiped: roles.sql.
TRUNCATE auth.users CASCADE;
