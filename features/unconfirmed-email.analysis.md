# Unconfirmed email verification — impact analysis

Advanced-auth option, admin-switchable like the others (2026-07-06 decision).
Lives in the *auth* context ("users" app settings).

**Pivot (2026-07-06)**: the original idea — an app-level
`require_confirmed_email` switch — is impossible: GoTrue refuses the password
grant of an unconfirmed account itself (`email_not_confirmed`), whatever the
autoconfirm config, so the app never gets a session to accept or reject. The
clean block + message already exist (the error mapping). What was genuinely
missing is the way out: an unconfirmed user was **stuck** — no way to get the
confirmation mail again. The feature is therefore the **resend**, and the
admin switch gates the resend (`users.resend_confirmation_enabled`, default
true).

- **UI**: the login error state gains a one-click "Resend confirmation email"
  form (hidden email field carried from the failed attempt) — rendered only
  when GoTrue said `email_not_confirmed` and the switch is on. Plain form:
  the login page is not HTMX, errors re-render the full page.
- **Route**: `POST /auth/resend-confirmation` — anonymous, rate-limited,
  neutral response (like forgot-password: no account enumeration), audited
  `auth.confirmation_resent`; **404 when the switch is off**.
- **Domain**: `resend_confirmation(email)` → GoTrue `resend(type=signup)`.
- **Supabase config**: custom `confirmation` template carrying `token_hash` to
  the existing SSR `/auth/confirm?type=signup` route (mirror of recovery) —
  also upgrades the initial signup mail to land on our SSR route.
- **Surfaces**: no table, no migration, no event, no screen beyond the login
  error slot.
- **Tests**: an *unconfirmed* user is seeded via the admin API
  (`email_confirm=False`) — locally signup autoconfirms, so that is the only
  way such an account exists. The unlock scenario follows the real emailed
  link (mail catcher), not an admin shortcut.
