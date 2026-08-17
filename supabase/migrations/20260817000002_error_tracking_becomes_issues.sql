-- Error tracking stops saying "event". That word belongs to the business journal, and having
-- `error_events` sit next to `business_events` made two unrelated things read as one family.
--
-- The right pair was already in the code, in the model's own docstring — "One *issue*: every event
-- sharing a stack fingerprint, with its lifecycle" — and in the app's name, its status enum, its
-- console screen and the facts it emits (`issues.opened`, `issues.regressed`). So: an `issue` has
-- `issue_occurrences`. Python drops the qualifier the module already carries (`Issue`,
-- `Occurrence`); the table names keep it, because a table name is global.
--
-- Pure renames: no data moves, and Postgres carries the FK, the unique constraint and the primary
-- keys across on its own. Only the names an operator reads are restated here.

alter table public.error_groups rename to issues;
alter table public.error_events rename to issue_occurrences;
alter table public.issue_occurrences rename column group_id to issue_id;

alter index public.error_groups_last_seen_idx rename to issues_last_seen_idx;
alter index public.error_events_group_idx     rename to issue_occurrences_issue_idx;

alter trigger error_groups_updated_at on public.issues rename to issues_updated_at;
