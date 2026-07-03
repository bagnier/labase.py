create schema if not exists test;

grant usage on schema test to authenticated;
grant select, insert, update, delete on all tables in schema test to authenticated;
alter default privileges in schema test grant select, insert, update, delete on tables to authenticated;
