# OAuth social sign-in (Google, GitHub)

GoTrue does the OAuth dance; the app only starts it and lands the callback:

```
/auth/oauth/{provider}            /auth/callback?code=…
  app mints a PKCE pair,   →  GoTrue → provider → GoTrue  →  app exchanges the code
  parks the verifier in a                                    (grant_type=pkce) and
  5-min httpOnly cookie                                      issues the session cookies
```

- Buttons appear on the sign-in and register pages when the `users` app settings
  `oauth_google_enabled` / `oauth_github_enabled` are switched on in the console.
- First OAuth visit bootstraps the personal organisation (same `UserCreated`
  chain as sign-up; the handler is idempotent for returning visitors).
- A user with TOTP enrolled gets the same two-factor step-up as a password
  sign-in before the session is issued.
- **Account merge** is GoTrue's: a provider identity whose *verified* email
  matches an existing account is linked into that account (`auth.identities`),
  never duplicated. Unverified matches are refused (anti-takeover).

## Testing status — read before trusting

Sincere E2E against real Google/GitHub is impossible, so coverage is split
(2026-07-06 decision):

- unit tests cover the PKCE pair, the authorize URL and the code exchange;
- E2E (both drivers) covers: buttons appear iff the switch is on, and starting
  the flow redirects to GoTrue's `/auth/v1/authorize` for the right provider;
- the provider round-trip itself is **manual** — checklist below.

## Manual verification, local stack

1. Create the provider app:
   - GitHub: Settings → Developer settings → OAuth Apps → New. Callback URL:
     `http://localhost:54321/auth/v1/callback`.
   - Google: Cloud Console → Credentials → OAuth client ID (Web). Same redirect URI.
2. Put the credentials in the repo-root `.env` (the Supabase CLI reads it):

   ```
   SUPABASE_AUTH_EXTERNAL_GITHUB_CLIENT_ID=…
   SUPABASE_AUTH_EXTERNAL_GITHUB_SECRET=…
   ```

3. Uncomment the `[auth.external.github]` (and/or google) block in
   `supabase/config.toml`, then `supabase stop && supabase start`.
4. Switch `oauth_github_enabled` on in `/console/users`.
5. Sign out, open `/auth/login`, click **Continue with Github** and complete the
   provider consent. You must land signed-in on `/profile`, with a personal org
   on first visit, and an `auth.oauth_signed_in` audit event.
6. Merge check: register the same email with a password first, verify it, then
   sign in via the provider — `auth.identities` gains a second row for the same
   user, no duplicate account.

## Production

Same two settings switches; provider credentials go in the Supabase dashboard
(Authentication → Providers) with the hosted callback
`https://<project-ref>.supabase.co/auth/v1/callback`, and your app origin must
be in the dashboard's redirect allow-list (`…/auth/callback`).
