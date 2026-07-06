# Email change — impact analysis

First of the advanced-auth options; **every one of them is admin-switchable via
declared settings** (2026-07-06 decision). This one lives in the *profile* app
(the form sits on the profile page, next to the password form).

- **GoTrue does the heavy lifting** (same doctrine as forgot/reset password):
  `PUT /auth/v1/user {"email": ...}` on the user's own token makes GoTrue send a
  confirmation to the **new** address; `verify_otp(token_hash, type="email_change")`
  finalizes and returns a fresh session. Zero app mail code.
- **Re-authentication**: the request requires the current password (same
  `WrongPassword` path as the password-change form) — a stolen session must not
  be able to steal the account.
- **Supabase config**: `[auth.email] double_confirm_changes = false` (single
  confirmation from the new address — the light path for a starting product) and
  a custom `email_change` template carrying `token_hash` to our SSR route
  (mirror of `recovery.html`).
- **Routes**:
  - `POST /profile/email` (profile context, `CurrentUser`) — re-auth, then ask
    GoTrue; audited `profile.email_change_requested`; **404 when
    `email_change_enabled` is false** and the form is hidden.
  - `GET /auth/confirm-email?token_hash=` (auth context, anonymous — the token IS
    the credential, like `/auth/reset-password`) — `verify_otp`, set the new
    session cookies, land on the profile; audited `profile.email_changed`.
- **profiles.email sync**: SQL trigger on `auth.users` (AFTER UPDATE OF email)
  updates `public.profiles.email` — one migration, works for every change path
  (app, Studio, support). No app-side sync to forget.
- **Settings**: `declare_app_settings("profile", [SettingDef("email_change_enabled",
  "boolean", "true", ...)])` — the profile app gains its first real settings and
  the live `AppSettings("profile")` handle (it declared an empty list until now).
- **Surfaces**: no dashboard/console overview change, no nav, no seeding, no new
  table (trigger only). Tests reuse the mailbox substrate (`wait_for_message`,
  token extraction generalized from `recovery_token`).
