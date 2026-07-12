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
  `auth.passkey_signed_in` recorded as a business event.
- GoTrue enforces the ceremonies, challenge replay protection, and requires an
  AAL2 session to add/remove a passkey when the user has 2FA enabled.

## Testing status — read before trusting

Both drivers exercise the **real GoTrue ceremony** (app → GoTrue → auth schema),
each at its own depth:

- **Browser driver** — the real thing, end to end: the e2e server runs on a
  pinned origin (`http://localhost:8801`, listed in `rp_origins`), so
  `static/js/passkeys.js` executes `navigator.credentials` against a Playwright
  **CDP virtual authenticator** (`WebAuthn.addVirtualAuthenticator`); the tests
  click the real **Add a passkey** / **Use a passkey** buttons, and the
  credential is carried into the visitor context for the discoverable sign-in.
- **API driver** — the server-side ceremony through a software authenticator
  (vendored in `tests/e2e/drivers/webauthn.py` on `cryptography` alone — the
  off-the-shelf ones pin a vulnerable range) that signs the configured rp
  origin.

Nothing is mocked in either path: GoTrue verifies every attestation/assertion.
