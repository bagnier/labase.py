-- PR #4 ships the labase-light/labase-dark identity and makes labase-light the
-- default theme. "light" stored in app_settings is the *old seeded default*, not
-- an admin's choice (defaults are persisted at first mount) — flip it so existing
-- installs adopt the identity. An admin who wants daisyUI "light" back can still
-- pick it in /console: it stays in the selectable roster.
update public.app_settings
set value = 'labase-light'
where app = 'appearance' and key = 'theme' and value = 'light';
