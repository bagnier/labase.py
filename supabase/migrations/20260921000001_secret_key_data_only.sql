-- The secret key reads and writes data, never TRUNCATE or TRIGGER: a leaked key would wipe a
-- table past RLS or plant a trigger on every tenant's writes. On today's tables and tomorrow's.
-- Revoke-all-then-grant: the linter's dialect predates MAINTAIN.
revoke all on all tables in schema public from service_role;
grant select, insert, update, delete on all tables in schema public to service_role;

-- The journal keeps its one writer, `record_business_event`: the secret key only reads it.
revoke insert, update, delete on public.business_events from service_role;

alter default privileges for role postgres in schema public
revoke all on tables from service_role;
alter default privileges for role postgres in schema public
grant select, insert, update, delete on tables to service_role;
