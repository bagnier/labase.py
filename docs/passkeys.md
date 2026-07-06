# Passkeys (WebAuthn)

Passwordless, phishing-resistant sign-in on GoTrue's **beta** passkeys API
(v2.19x, feature-flagged). Two switches gate it:

1. `supabase/config.toml` — `[auth.passkey] enabled = true` plus the
   `[auth.webauthn]` rp block (already set for local dev: rp_id `localhost`,
   origin `http://localhost:8000`). Hosted: enable in the dashboard when the
   beta reaches it, or via GoTrue env on self-hosted.
2. The `users.passkeys_enabled` console switch (default **off** — the upstream
   API is experimental and may change; turning it on is a conscious choice).

## What ships

- **Profile → Passkeys**: add (WebAuthn ceremony in `static/js/passkeys.js`),
  list, remove. Server proxies GoTrue (`/profile/passkeys/*`) because the
  access token lives in an httpOnly cookie the JS cannot read.
- **Login page**: "Use a passkey" button → discoverable-credential sign-in
  (`/auth/passkeys/options` + `/verify`), session cookies issued on success,
  `auth.passkey_signed_in` audited.
- GoTrue enforces the ceremonies, challenge replay protection, and requires an
  AAL2 session to add/remove a passkey when the user has 2FA enabled.

## Testing status — read before trusting

A real browser WebAuthn prompt cannot run in E2E: GoTrue pins `rp_origins` and
the in-process browser test server runs on a random port. Both drivers instead
run the **real server-side ceremony** (app → GoTrue → auth schema) through a
software authenticator (vendored in `tests/e2e/drivers/webauthn.py` on
`cryptography` alone — the off-the-shelf ones pin a vulnerable range) that
signs the configured rp origin; the browser driver additionally asserts the
visible affordances. The one thing never exercised automatically is
`navigator.credentials` itself — verify it manually once per browser family:
enable the switch, add a passkey from `/profile`, sign out, click
**Use a passkey**.
