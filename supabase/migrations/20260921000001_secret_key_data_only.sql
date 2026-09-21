-- The secret key (`service_role`) reads and writes data; it does not reshape tables. Supabase's
-- default privileges also hand it TRUNCATE, TRIGGER, REFERENCES and MAINTAIN on every table in
-- `public` — a leaked key could then wipe a table past RLS in one statement, or plant a trigger
-- that runs on every tenant's writes. Reset to the four data privileges on today's tables, and on
-- what `postgres` creates tomorrow (the next app's tables, the log partitions rolled each day).
-- Spelled as revoke-all-then-grant: the linter's dialect predates MAINTAIN.
revoke all on all tables in schema public from service_role;
grant select, insert, update, delete on all tables in schema public to service_role;

-- The journal keeps its one writer, `record_business_event`: the secret key only reads it.
revoke insert, update, delete on public.business_events from service_role;

alter default privileges for role postgres in schema public
revoke all on tables from service_role;
alter default privileges for role postgres in schema public
grant select, insert, update, delete on tables to service_role;
