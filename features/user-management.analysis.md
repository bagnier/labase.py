# User management — impact analysis

Closes the "server user management" console-ops gap (JHipster parity) and the
"disable / delete user" advanced-auth item, admin-switchable like the rest
(`users.user_management_enabled`, default true).

- **Where**: `/console/accounts` — a dedicated auth-context console screen
  (mirror of `apps/issues`' mounting: registered BEFORE the settings context so
  it precedes the `/console/{app}` catch-all; `/console/users` is taken by the
  "users" app settings page).
- **Data**: GoTrue admin API (accounts live in auth.users, not an app table):
  list = `list_users` (email, created, confirmed, banned/deleted state),
  filtered of soft-deleted accounts.
- **Actions** (all audited at warning level, admin-gated, 404 to non-admins):
  - **disable** = GoTrue `ban_duration: "876000h"` (~100 years); **enable** =
    `ban_duration: "none"`. Banned sign-ins get a clear mapped message.
  - **delete** = same path as self-serve account deletion: `UserDeleted` event
    on the bus (organizations cleanup joins the request's admin session) +
    profile row removal + GoTrue **soft delete**.
  - an admin cannot disable or delete their own account (guard, 400).
- **Settings**: `SettingDef("user_management_enabled", "boolean", "true")` in
  the existing "users" group; routes 404 when off.
- **Console overview**: the existing "users" card is untouched; the screen is
  its natural drill-down.
- **Surfaces**: no table, no migration (GoTrue-only state), no new events
  (reuses `UserDeleted`).
- **Tests**: disable → sign-in rejected; enable → restored; delete → gone from
  the list and sign-in rejected; non-admin 404; switch off → 404.
