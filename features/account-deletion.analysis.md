# Account deletion — impact analysis

Advanced-auth option, admin-switchable (`profile.account_deletion_enabled`,
default true). Lives in the *profile* context — the Danger zone placeholder on
/profile finally becomes real.

- **Route**: `DELETE /profile` (`CurrentUser`), re-authenticated with the
  current password (same `WrongPassword` path as password/email change — a
  stolen session must not be able to destroy the account). The Danger-zone form
  uses `hx-delete` + `hx-confirm`; success clears the auth cookies and
  redirects (HX-Redirect / 303) to `/auth/login?info=account_deleted`.
  404 when the switch is off, form hidden.
- **What deletion means** (assumed limits, stated plainly):
  - app data: the user's personal organisation(s) — orgs where they are the
    only member — are deleted through the request session (SQL cascades take
    care of org-scoped rows); memberships in shared orgs are removed; the
    profile row is deleted. Shared orgs themselves survive.
  - GoTrue: **soft delete** (`should_soft_delete=true`) — sign-in becomes
    impossible immediately. Hard-deleting auth.users here would deadlock the
    API test driver (its open transaction holds FK key-share locks on the
    user row) and would also erase the deletion audit trail; a later purge job
    on the async substrate can hard-delete cold soft-deleted accounts
    (out of scope today).
- **Audit**: `profile.account_deleted` at warning level, before the deletion.
- **Settings**: second `SettingDef` in the existing "profile" group.
- **Surfaces**: no new table/migration (deletes only), no event, no overview
  change. `/auth/login` gains an `account_deleted` info message.
- **Tests**: after deletion the same credentials must be rejected; wrong
  password path keeps the account; switch-off hides the form (browser) and
  404s the route (API). The deleted address is tracked for teardown cleanup.
