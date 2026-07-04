## remediation (audit 2026-07-03)

### 1. doc-sync — executable docs must not lie (agent-driven base ⇒ doc drift = prod bug)

- [x] fix `.claude/skills/feature/references/build.md`: `mount(app, host)` → `mount(host)` (L127-142, L208)
- [x] fix `build.md` L119 + `impact.md` L28: `ShellOrgQuery` / `apps/profile/contract/shell.py` → `OrgNavQuery` / `apps/organizations/contract/shell.py`
- [x] fix `build.md` L155: Tailwind 3.4 → 4.x; document daisyui 5.x (absent from skill, README and CLAUDE.md)
- [x] README: `mount(app, host)` → `mount(host)` (L50, L52, L114)
- [x] README structure: add `calendar/`, `styleguide/`, `client/`, `docs/schema*`; add Biome to quality tools; state calendar's status (demo or core?)
- [x] README: soften "no mocking the persistence layer" — true for E2E, unit suite does mock sessions/engine (organizations, auth, health)

### 2. contract-readiness — what any client contract would re-pay

- [ ] email — two routes, lightest possible:
  - auth lifecycle (forgot/reset password, confirmation, email change) → GoTrue calls + Supabase email templates, zero app code
  - app transactional (org invitations — token exists but is never sent) → tiny `Mailer` port in `apps/shared/email.py` (`Email` dataclass + `Protocol` + `SmtpMailer` via aiosmtplib, env-configured); Jinja2 for text/html; sent via `BackgroundTasks` (audit-style best-effort), moves behind the async-substrate queue later without changing the port
  - dev: SMTP → local Supabase mail catcher (Inbucket/Mailpit, SMTP 54325) — same inbox as GoTrue mail, nothing to install; prod: any SMTP provider, no vendor SDK
  - tests: unit → `FakeMailer` recording sent emails (single injection point, clock-style); E2E sincere → driver substrate reads the mail catcher HTTP API (mail really sent, really fetched, both drivers share one mailbox client)
- [ ] forgot/reset password (see advanced auth below)
- [ ] prod deployment: compose/manifest, secrets story beyond `.env` files, deploy doc
- [ ] monitoring: metrics + error tracking (Sentry) on top of health probes; backup/PITR doc
- [ ] rate limiter: in-memory slowapi → shared store (first client of Postgres-as-Redis)
- [ ] `SettingsChanged` live-reload is in-process only — with N instances, only the one handling the POST reloads; others serve stale settings silently. Reload via Postgres NOTIFY or TTL re-read
- [x] honor `$PORT` in `docker/entrypoint.sh` (currently hardcoded 8000)

### 3. async substrate — prerequisite to every Postgres-as-X brick

- [ ] durable event table (outbox / pgmq-style, `FOR UPDATE SKIP LOCKED`)
- [ ] worker entrypoint (process or lifespan task) — nothing long-running exists today
- [ ] background RLS convention: synthesized tenant claims via `set_config`, not blanket BYPASSRLS
- [ ] then: email sending, FTS indexing, cache expiry become consumers of this brick

### 4. DX gradation — prototype fast, harden later

- [ ] `/feature` skill: add a prototype mode (merged scenarios+impact, optional mockup, API driver only; browser mixin at stabilization)
- [ ] promote pages' `_mutation_response` + HX-Redirect patterns into `apps/shared/http/` (bifurcation helpers beyond `render_list`)
- [ ] scaffold `make new-context NAME=x` (or skill) — the 23-file checklist is mechanical
- [ ] `new-product` skill: delete demos (incl. todos FK/policy inside `000004_organizations.sql`), rename ~50 hardcoded "labase"
- [ ] test helpers: `given_helpers` cross-imports between test suites (11 sites) — bless or move to a shared test contract

### 5. simplification — closing windows first

- [ ] decide `client/` fate: unused → remove/extract; used → document it
- [ ] `learning` contradicts its own hexagonal lesson: no port Protocol (organizations has one), only repo not extending `OrgScopedRepository` — align or re-label the demo

#### doublons (by payoff)

- [x] ORM mixins in `shared/persistence/base.py` (`UUIDPk`, `OrgScoped`, `Versioned`, `Timestamped`) — ~12 models recopy the same 6 lines (~60-70 lines, lowest risk)
- [ ] `integration.py` ritual: extract `overview_from_count()`, `pluralize()`, `seed_with_owner()` helpers (~120-160 lines across 5 contexts) — factor the bodies, NOT the wiring (mount stays explicit, cf. non-goal above)
- [ ] Jinja macro `overview_card()` — 5 carbon-copy `_overview.html` ("Open →" link coded 5 different ways); pills as `badge`; component class for the `card bg-base-100 border…` shell respelled ×25
- [ ] `audit(bg, event, user, org_id, **fields)` helper — 38 `record_audit_event` calls repeat the same first 5 args
- [ ] `PositionedRepository` mixin — `move_above` algorithm duplicated todo/pages (fix the version bypass there too)
- [ ] `OrgScopedRepository.default_order` — kills 4 `all()` overrides, todo's redundant `count()`, duplicated `count_all()`
- [ ] a11y parity: `<section aria-label>` on recent pages (pages/settings/calendar views), `aria-live` on HTMX-swapped lists, use `input_field()` macro in `pages/form.html`

### 7. positioning

- [x] README: state the intent — this base is optimized for agent-driven development (skills as executable specs, dual-driver BDD as agent verification substrate, worktrees for parallel agents); it justifies the ceremony
- [ ] split this ROADMAP: "contract-readiness" vs "Postgres-as-X demonstrators"; move the Supabase feature catalog to a separate note

## goals

### technical

- [ ] logs
- [ ] COW, soft deletion, soft update
- [ ] async task queue
- [ ] fulltext index - elastic
- [ ] documents - mango
- [ ] cache - redis
- [ ] messaging - kafka
- [ ] email
- [ ] prod deployment doc (secrets, env)
- [ ] https://12factor.net
- [ ] https://w.pitula.me/fintech-engineering-handbook/


### advanced auth

- [ ] @handle
- [ ] photo de profil
- [ ] disable / delete user
- [ ] Forgot password (/auth/forgot-password + /auth/reset-password)
- [ ] Password change (authenticated) — POST /profile/password
- [ ] Email change — POST /profile/email + SQL trigger to sync profiles.email
- [ ] Account deletion — DELETE /profile + cascade + logout
- [ ] Unconfirmed email verification — block login cleanly if email_confirmed_at is null
- [ ] Avatar — upload to Supabase Storage, the org_files pattern is directly reusable
- [ ] 2FA TOTP — Supabase Auth handles it natively, just wire up the UI flow
- [ ] OAuth social login (Google, GitHub) — callback page + merge with existing email account via auth.identities
- [ ] Passkeys / WebAuthn — auth.webauthn_credentials is already in the Supabase schema

### possible Supabase integrations

- [ ] AI Integrations - Enhance applications with OpenAI and Hugging Face integrations.
- [ ] Auth Hooks - Customize authentication flows with serverless functions.
- [x] Authorization via Row Level Security - Control the data each user can access with Postgres Policies.
- [ ] Auto-generated GraphQL API via pg_graphql - Fast GraphQL APIs using our custom Postgres GraphQL extension.
- [ ] Auto-generated REST API via PostgREST - RESTful APIs auto-generated from your database.
- [ ] Automatic Embeddings - Automated embedding generation using triggers and queues.
- [x] CLI - Use our CLI to develop your project locally and deploy.
- [ ] Captcha protection - Add Captcha to your sign-in, sign-up, and password reset forms.
- [x] Client Library - Python - Integrate Supabase easily into your Python applications.
- [ ] Content Delivery Network - Cache large files using the Supabase CDN.
- [ ] Cron - Schedule recurring Jobs in Postgres.
- [ ] Custom Identity Providers - Connect any OAuth2 or OIDC identity provider to Supabase Auth.
- [ ] Database Webhooks - Trigger external payloads on database events.
- [ ] Database backups - Projects are backed up daily with Point in Time recovery options.
- [ ] Declarative Schemas - Simplify database management with declarative schema files.
- [ ] Dedicated Poolers - Co-located connection pooler for maximum performance.
- [ ] Deno Edge Functions - Globally distributed TypeScript functions to execute custom business logic.
- [ ] Functions
- [ ] Email Templates - Customizable email templates for all authentication flows.
- [x] Email login - Build email logins for your application or website (confirmations disabled locally).
- [x] File storage - Supabase Storage makes it simple to store and serve files.
- [ ] Foreign Data Wrappers - Query external data sources as Postgres tables.
- [ ] Foreign Key Selector - Easily manage foreign key relationships between tables.
- [ ] Image transformations - Optimize and resize images on-the-fly directly from your Supabase storage buckets.
- [ ] JWT Signing Keys - Asymmetric key management for enhanced JWT security.
- [ ] Log Drains - Export logs to Datadog, Grafana, Sentry, S3, and more — now available on Pro.
- [ ] Logs & Analytics - Gain insights into your application's performance and usage.
- [ ] Multi-Factor Authentication (MFA) - Add an extra layer of security to your application with MFA.
- [ ] Network restrictions - Restrict IP ranges that can connect to your database.
- [ ] OAuth2.1 Server - Turn your project into an OAuth 2.1 identity provider.
- [ ] Passwordless login via Magic Links - Build passwordless logins via magic links for your application or website.
- [ ] Persistent Storage - Mount S3 buckets for 97% faster Edge Function cold starts.
- [ ] Phone logins - Provide phone logins using a third-party SMS provider.
- [ ] Policy Templates - Quickly implement common security policies.
- [ ] Postgres Extensions - Enhance your database with popular Postgres extensions.
- [ ] Postgres Roles - Managing access to your Postgres database and configuring permissions.
- [x] Postgres database - Every project is a full Postgres database.
- [ ] Broadcast - Send messages between connected users through websockets.
- [ ] Broadcast Authorization - Control access to broadcast channels in real-time.
- [ ] Broadcast from the Database - Trigger broadcast messages directly from Postgres.
- [ ] Postgres changes - Receive your database changes through websockets.
- [ ] Presence - Synchronize shared state between users through websockets.
- [ ] Presence Authorization - Manage presence information securely in real-time.
- [ ] Reports & Metrics - Monitor your project's health with usage insights.
- [ ] Resumable uploads - Upload large files using resumable uploads.
- [ ] S3 compatibility - Interact with Storage from tools which support the S3 protocol.
- [ ] SQL Editor - A powerful interface for writing and executing SQL queries.
- [ ] SSL enforcement - Enforce secure connections to your Postgres clients.
- [ ] SSO with SAML - Enterprise single sign-on using SAML protocol.
- [ ] Security & Performance Advisor - Optimize your database security and performance effortlessly.
- [ ] Server-side Auth - Helpers for implementing user authentication in popular server-side languages.
- [ ] Smart Content Delivery Network - Automatically revalidate assets at the edge via the Smart CDN.
- [ ] Social login - Provide social logins from platforms like Apple, GitHub, and Slack.
- [ ] Supavisor - A scalable connection pooler for Postgres.
- [ ] Third-Party Authentication - Trust JWTs from external authentication providers.
- [ ] User Impersonation - Experience your application as any user.
- [ ] Vector Database - Store vector embeddings right next to the rest of your data.
- [ ] Visual Schema Designer - Design your Postgres database schema with an intuitive interface.
- [ ] Web3 Authentication - Wallet-based authentication for Ethereum and Solana.
