# Two-factor authentication (TOTP) — impact analysis

Last advanced-auth option of the lot; GoTrue owns the crypto (factors,
challenges, AAL), the app wires the two UI moments. Admin-switchable via
`users.two_factor_enabled` (default true); switching it off also *bypasses*
the challenge at sign-in — the admin escape hatch when someone loses their
authenticator.

- **Enrolment** (profile page, auth-owned section like password):
  `POST /profile/2fa/enroll` → GoTrue `POST /auth/v1/factors` on the user's
  own token → secret + otpauth URI rendered (text, no QR lib — the URI is
  pasteable and QR can come later); `POST /profile/2fa/verify {code}` →
  challenge+verify → factor verified. `DELETE`-equivalent unenroll with
  password re-auth. Audited.
- **Sign-in step-up**: after password login, if the account has a verified
  TOTP factor (and the switch is on) the session is NOT issued: the AAL1
  tokens go into short-lived (5 min) httpOnly cookies, a challenge is created
  and the login page renders a code form. `POST /auth/mfa {code}` verifies →
  GoTrue returns the AAL2 session → real cookies set, temp cookies dropped.
- **Domain calls**: stateless httpx against `/auth/v1/factors*` (same shape as
  `update_password`) — the supabase-py MFA client wants a stateful session.
- **Tests**: `pyotp` (dev dependency) generates real codes from the enrolled
  secret on both drivers; wrong-code path uses "000000".
- **Surfaces**: no table, no migration, no event; one new declared setting;
  login template gains the challenge state; profile template a Two-factor
  section (gated).
