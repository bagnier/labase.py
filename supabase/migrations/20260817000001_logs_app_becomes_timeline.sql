-- The unified viewer stops being named after one of the three sources it merges: `apps/logs`
-- becomes `apps/timeline`.
--
-- Settings are persisted per app name (`app_settings.app`, seeded on declaration at mount), so a
-- rename orphans the rows an admin edited: on the next boot the app would re-seed its declared
-- defaults and silently lose both the tuned firehose level and its on/off switch. Carry them over.
--
-- The `log_level` key itself is unchanged — it still gates the firehose, only its owning group
-- moves. `org_app_settings` keeps its DB column named `app` (the ORM attribute is `app_name`).

update public.app_settings     set app = 'timeline' where app = 'logs';
update public.org_app_settings set app = 'timeline' where app = 'logs';
