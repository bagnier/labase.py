## remediation (audit 2026-07-03)

### contract-readiness — what any client contract would re-pay

- [ ] email — two routes, lightest possible:
  - [ ] auth lifecycle (forgot/reset password, confirmation, email change) → GoTrue calls + Supabase email templates, zero app code
    (forgot/reset ✓ and confirmation ✓ shipped; email change still open)
  - [x] app transactional (org invitations — token exists but is never sent) → tiny `Mailer` port in `apps/shared/email.py` (`Email` dataclass + `Protocol` + `SmtpMailer` via aiosmtplib, env-configured); Jinja2 for text/html; sent via `BackgroundTasks` (audit-style best-effort), moves behind the async-substrate queue later without changing the port
  - [x] dev: SMTP → local Supabase mail catcher (Inbucket/Mailpit, SMTP 54325) — same inbox as GoTrue mail, nothing to install; prod: any SMTP provider, no vendor SDK (`SMTP_*` env vars)
  - [x] tests: unit → `FakeMailer` recording sent emails (single injection point, clock-style); E2E sincere → driver substrate reads the mail catcher HTTP API (mail really sent, really fetched, both drivers share one mailbox client — `tests/e2e/drivers/mailbox.py`)
- [x] forgot/reset password (see advanced auth below)
- [ ] prod deployment: compose/manifest, secrets story beyond `.env` files, deploy doc
- [ ] monitoring: metrics + error tracking (Sentry) on top of health probes; backup/PITR doc
- [x] rate limiter: in-memory slowapi → shared store (first client of Postgres-as-Redis)
  → slowapi removed; fixed-window counters in `rate_limit_counters` (atomic upsert,
  multi-instance correct, fail-open, opportunistic per-key cleanup — a real purge
  job joins the async substrate later)
- [x] `SettingsChanged` live-reload is in-process only — with N instances, only the one handling the POST reloads; others serve stale settings silently. Reload via Postgres NOTIFY or TTL re-read
  → TTL re-read: `SettingsRefresher` lifespan task per process (`settings_refresh_seconds`,
  default 30s, 0 disables) re-reads `app_settings` and re-emits `SettingsChanged`
  locally on diff; local edits absorbed so the emitting instance never double-fires

### async substrate — prerequisite to every Postgres-as-X brick

- [x] durable event table (outbox / pgmq-style, `FOR UPDATE SKIP LOCKED`)
  → `task_queue` migration + `apps/shared/queue.py`: `enqueue()` writes through the
  caller's session (outbox: task exists iff the business tx commits); app roles
  get INSERT-only, claiming is admin work; retry with backoff then park as failed;
  recurring singletons re-enqueue on completion
- [x] worker entrypoint (process or lifespan task) — nothing long-running exists today
  → `TaskWorker` lifespan task per process (`task_worker_interval_seconds`, 0 disables);
  a separate process entrypoint can reuse the same class later
- [x] background RLS convention: synthesized tenant claims via `set_config`, not blanket BYPASSRLS
  → tasks carrying `user_id` run their handler on a user-role session with
  `{"sub": user_id, "role": "authenticated"}` claims; without `user_id` → admin session
- [ ] then: email sending, FTS indexing, cache expiry become consumers of this brick
  → first consumer shipped: `rate_limit.purge` (hourly recurring); email still goes
  through BackgroundTasks (its port makes the move mechanical)

### DX gradation — prototype fast, harden later

- [x] promote pages' `_mutation_response` + HX-Redirect patterns into `apps/shared/http/` (bifurcation helpers beyond `render_list`)
  → was already done (`mutation_response`/`delete_response` in `apps/shared/http/responses.py`,
  unit-tested); migrated the last hand-rolled HX-Redirect (org creation) onto it
- [ ] scaffold `make new-context NAME=x` (or skill) — the 23-file checklist is mechanical
  (2026-07-05: out of scope for now)
- [ ] `new-product` skill: delete demos (incl. todos FK/policy inside `000004_organizations.sql`), rename ~50 hardcoded "labase"
- [x] test helpers: `given_helpers` cross-imports between test suites (11 sites) — bless or move to a shared test contract
  → decided 2026-07-05: **blessed** — cross-imports between test suites are fine;
  the import-linter contracts already exempt `apps.*.tests.**`

### simplification — closing windows first

- [x] decide `client/` fate: unused → remove/extract; used → document it
  → decided 2026-07-05: **keep** (candidate substrate for the perf smoke tests);
  still to do: document it in README
- [x] `learning` contradicts its own hexagonal lesson: no port Protocol (organizations has one), only repo not extending `OrgScopedRepository` — align or re-label the demo
  → aligned: `ReviewRepositoryProtocol` port + `review_card` domain use-case (daily
  cap + scheduling moved out of the router); the repo deliberately stays outside
  `OrgScopedRepository` (multi-model query surface, documented in its docstring)
- [x] `PositionedRepository` mixin — `move_above` algorithm duplicated todo/pages (fix the version bypass there too)
  → mixin + `Positioned` model column in `apps/shared/persistence/`; the version
  bypass was already fixed by d32b205 (load-then-mutate-then-flush, 409 handler)

## jhipster gap analysis (2026-07-05)

Compared the base against JHipster v8/v9 and JHipster Lite (archived 2025-08-04,
continued as Seed4J by the same authors). Kept only the gaps worth closing here —
multi-CI generators, K8s/multi-cloud, SPA frontends, Sonar, and external
Kafka/Elastic/Redis modules are deliberately NOT borrowed (they contradict the
Supabase/Postgres-as-everything bet or duplicate ruff/ty/coverage/vulture).

### high value

- [x] **architecture tests** — README claims "domain never imports infra; apps never
  import each other; principles are mechanically verifiable" but nothing verifies it
  (JHipster ships ArchUnit by default; Lite makes it a pillar). Use `import-linter`
  in `make lint` with contracts: `domain/` must not import `infra/`; no cross-context
  imports except via `contract/`; only `apps/main.py` may know several contexts.
  ~Half a day, best value/effort of this list. Critical for agent-written code.
  → `[tool.importlinter]` in `pyproject.toml`: 13 contracts (domain⇏infra,
  shared⇏contexts, per-context internals protected — cross-context only via
  `contract/`); `lint-imports` wired into `make lint` and `make fix`. Tests exempt
  (given_helpers question tracked in DX gradation).
- [x] **CSRF protection** — JWT in httpOnly cookie + HTMX forms is exactly the
  CSRF-vulnerable profile, and there is no protection today (no token, no
  `Origin`/`Sec-Fetch-Site` check). JHipster enables CSRF in every cookie-based mode.
  Lightest fix compatible with HTMX (no token plumbing): middleware rejecting
  mutations (POST/PUT/PATCH/DELETE) when `Sec-Fetch-Site` is present and not
  `same-origin`/`none`, falling back to an `Origin` vs host check for older agents.
  → `csrf_protect` middleware in `apps/shared/http/security.py`, mounted by the
  shared `mount()`; rejections logged (`csrf.rejected`) and unit-tested.
- [ ] **`make upgrade-base`** — JHipster's `jhipster upgrade` solves the cloned-app
  problem: regenerate on an orphan `jhipster_upgrade` branch with old then new
  version, 3-way git merge into the product branch, customizations survive. Our
  version: products clone labase, then pull base improvements via a `base` git remote
  + dedicated merge branch (or rebase of base commits). Realistic here precisely
  because demos are disposable and boundaries are hard — conflicts concentrate in
  `apps/shared/` and `main.py`. Pairs with the `new-product` skill (DX gradation):
  together they close the full lifecycle clone → develop → keep benefiting.
  Document the merge protocol (what a product must never edit vs owns fully).

### medium value

- [ ] **console ops screens** — JHipster generates admin screens we lack:
  - metrics: `/metrics` Prometheus endpoint + console page (joins the monitoring
    TODO in contract-readiness)
  - runtime log-level control: change structlog/stdlib levels from the console
    without redeploy — cheap and very useful in prod
  - server user management: list/disable/delete users from the console (joins the
    advanced-auth "disable / delete user" TODO)
- [ ] **i18n** — JHipster ships 45+ languages with a navbar switcher; all our UI
  strings are hardcoded English. Jinja2 route: Babel/gettext extraction, per-request
  locale (cookie or `Accept-Language`), catalogs per context. Expensive to retrofit
  later — decide early: if target products are French-speaking this is urgent,
  otherwise defer consciously.
  → decided 2026-07-05: **consciously deferred** — out of scope for now.
- [ ] **perf smoke tests** — JHipster generates one Gatling simulation per entity.
  Equivalent: a Locust smoke per context, reusing the generated OpenAPI client in
  `client/` — which would finally give `client/` a reason to exist (see
  simplification: "decide client/ fate").

### options (DO NOT IMPLEMENT)

- [ ] **declarative entity scaffolding** — JHipster's killer feature: `jhipster entity`
  + JDL generate entity/repo/service/DTO/CRUD screens/tests/migration, idempotently
  (definition persisted in `.jhipster/*.json`, regenerable later). The planned
  `make new-context` (see DX gradation above) should aim higher than a 23-file
  checklist: a declarative entity definition (fields, validations, relationships,
  pagination/filter options) driving a `/new-context` skill + deterministic templates
  that emit the full bounded context — `domain/`, `infra/`, templates, SQL migration
  **with RLS policies**, Gherkin feature, both driver mixins, `mount()` wiring.
  Persist the definition inside the context (regeneration story). Bundle a standard
  list-endpoint convention: pagination + per-field filter query params (JHipster's
  `*Criteria`/`QueryService` equivalent) — today only the audit viewer has cursor
  pagination, every other list is ad hoc.
- [ ] **module landscape** — Lite's strong idea: incremental modules applied à la
  carte, visualized as a dependency graph (`/landscape` UI). Our apps already ARE
  modules (declarative mount, traceless deletion); borrow the formalization, not the
  tool: document upcoming bricks (email, queue, FTS, cache) as optional modules with
  explicit dependencies ("FTS requires the async worker"), not a flat TODO list.
  Optionally a console "landscape" page: bricks installed/available.
- [ ] **named permissions** — Lite's "Kipe" authorization module: permission model
  beyond binary roles. Our owner/member is binary; keep in mind for the first
  client contract needing custom roles. Not urgent.

## error tracking — Sentry-as-Postgres brick (2026-07-05)

Build self-hosted error tracking as a bounded context (`apps/issues/`), replacing the
"error tracking (Sentry)" buy in contract-readiness with a build. Best candidate for
the first *visible* Postgres-as-X brick: unlike cache/queue it has a product surface
(a console screen) that demonstrates the thesis instead of staying plumbing. No Python
boilerplate ships this.

What Sentry's value actually is: not capture (trivial) but **grouping** — thousands of
events deduped into few *issues* via stack-trace fingerprinting, with a lifecycle
(new → unresolved → resolved → **regressed**). All replicable on Postgres.

- [ ] **capture** — FastAPI exception handler + two already-identified points: event-bus
  handler failures (`collect` already logs them) and `BackgroundTasks` failures.
  Audit doctrine verbatim: best-effort, never blocks — persistence via background
  task; if the DB is down, fall back to the structured log and nothing else. The
  error handler must never itself fail.
- [ ] **fingerprinting** — hash of (exception type, top-N in-app frames normalized to
  file:function). Never the message (variable values). Allow a manual fingerprint
  override for weird cases.
- [ ] **storage** — two tables, no RLS (server-level admin data, AdminSession):
  - `error_groups`: fingerprint, title, first_seen/last_seen, count, status
    (new/unresolved/resolved/ignored/regressed), first/last version
  - `error_events`: group FK, JSONB context (stack, request path, user_id, org,
    **request_id** — pivots each event to its correlated structlog lines, a link
    Sentry SaaS cannot offer)
- [ ] **lifecycle & regressions** — resolve/ignore buttons in console;
  `resolved_in_version` = git SHA already in the Docker env; event arriving on a
  resolved group with a later version → `regressed`. Sentry's most useful feature,
  one column + one if.
- [ ] **console screen** — issues list sorted by volume/recency with status badges;
  detail view: stack trace, context, recent occurrences (cursor pagination — reuse
  the audit viewer pattern); "N unresolved" stat in console overview. Standard app
  shape: `mount()`, declared settings (retention days, alerting on/off), feature
  switch.
- [ ] **alerting** — emit typed `IssueOpened` / `IssueRegressed` on the bus → the
  planned `Mailer` (contract-readiness) subscribes. Emitter never knows subscribers.
- [ ] **retention** — periodic purge as a consumer of the async substrate (like cache
  expiry, FTS indexing).

Assumed limits (don't over-promise): no JS sourcemaps, no perf tracing, no statistical
spike detection, dumber grouping on edge cases. Positioning: the error tracking of a
starting product — enough until real volume; the Sentry SDK can be added later without
conflict (they coexist fine).

Optional extensions, later: frontend JS error capture (`window.onerror` → POST
endpoint; mind anonymous rate limiting) and basic spike detection (count per hourly
window).

## load metrics — Metrics-as-Postgres brick (2026-07-05)

Two layers sharing ONE collector; don't conflate them. Together they close the
"metrics" half of the monitoring TODO in contract-readiness (error tracking above
closes the other half).

- [ ] **layer 1: `/metrics` Prometheus endpoint** — standard exposition (requests per
  route, latency histograms, status codes, in-flight, asyncpg pool stats), via
  `prometheus-fastapi-instrumentator` or a hand-rolled middleware. Cheap, the interop
  standard (Grafana/alertmanager/any host), commits to nothing. Alone it *shows*
  nothing without a Prometheus server — hence layer 2.
- [ ] **layer 2: console "Load" screen** — what a starting product actually wants: see
  its load in the admin console, not run a Grafana stack.
  - **in-memory accumulator** in the middleware (`RequestLogger` is already on the
    path): per route template, counts requests/errors and fills fixed-boundary
    latency histogram buckets. This single accumulator feeds BOTH the `/metrics`
    text exposition (instant read) and the Postgres flush (history) — collection is
    written once.
  - **aggregated periodic flush** to Postgres: one row per (route, minute bucket) —
    NEVER one row per request. This is what makes time-series-in-Postgres viable:
    at 100 req/s that's a few rows/minute, not 6000. p50/p95 computed from the
    histogram buckets, exactly like Prometheus does.
  - **console screen**: traffic sparklines, top routes, p95, error rate (natural
    link to the issues screen). daisyUI `stat` components already exist.
  - **retention/downsampling**: minute → hour after ~7 days, purge — third consumer
    of the async substrate (after email and error-events purge).
  - **DB side: link out, don't rebuild** — hosted Supabase already covers it
    (dashboard Reports, Query Performance on pg_stat_statements, advisors,
    Prometheus endpoint). Just add links in the console to the relevant Supabase
    pages: local → Studio (`localhost:54323`), hosted → dashboard pages (needs the
    project ref in config to build URLs). App-side HTTP metrics remain the
    differentiation.
- multi-instance note: each process flushes its own rows, the screen aggregates in
  SQL — unlike the `SettingsChanged` live-reload gap, multi-instance is trivially
  correct here.

Assumed limits: no distributed tracing, fixed label set (route/method/status — no
arbitrary cardinality), minute granularity. Beyond that, layer 1 is already there to
plug real tooling without rewriting anything.

## python boilerplate gap analysis (2026-07-05)

Compared against the Python field: fastapi/full-stack-fastapi-template (44k★, React
SPA, no teams/billing), cookiecutter-django (13.5k★, infra only), SaaS Pegasus
(Django, $449+, THE feature gold standard), FastroAI/FastSaaS/FastLaunchAPI (small
commercial FastAPI kits), fastapi_supabase_template (350★, API-only, best
Supabase+Python effort).

Validated differentiators — nobody ships these, keep investing: (a) RLS-enforced
multi-tenant isolation driven from Python (Supabase starters are overwhelmingly
Next.js; Basejump, the closest RLS+teams starter, is SQL/Next.js); (b) Jinja2+HTMX
SSR with content negotiation as a full kit (existing FastAPI+HTMX starters are
sub-200★ demos); (c) audit trail (absent from every candidate incl. Pegasus);
(d) BDD dual-driver tests (no candidate uses Gherkin at all). Pegasus shipping
Claude/Cursor rules + MCP confirms agent-driven DX is now a selling point.

Gaps revealed (most already tracked: email, jobs, i18n, 2FA, monitoring — see
above). New items:

- [ ] **billing — the one fully missing link** in the contract-readiness reasoning
  ("what any client contract would re-pay"). The core of every commercial
  boilerplate's offer; the minimal credible SaaS-kit grammar is auth + teams +
  billing + email + jobs, and billing is the only piece entirely absent here.
  Shape: a `billing/` bounded context, standard mount; **subscription per org**
  (owner-managed); Stripe Checkout + customer portal (no card UI to build),
  webhook endpoint feeding typed events (`SubscriptionChanged`) on the bus;
  plan gates readable by other apps the same way declared settings are (e.g.
  `max_items_per_org` becomes plan-dependent); console overview stat (MRR,
  active subs). Keep the domain Stripe-agnostic behind a port (audit/Mailer
  doctrine) — Stripe adapter first, no vendor lock in domain code. Demo-app
  friendly: a fake "Pro plan" gating one demo feature shows the pattern.
  (2026-07-05: out of scope for now)
- [x] **per-org feature flags** (approved 2026-07-05) — app switches + declared settings cover the
  server-wide 80%; missing is the org-scoped flag ("beta for this customer").
  Small extension of the existing settings model (org_id column, org override
  screen); becomes plan-tier gating for free once billing exists.
  → `org_app_settings` table (console writes, org members read via RLS);
  `AppSettings.for_org(session, org_id)` merges overrides over server values;
  console app page gains a "Per-organisation overrides" section (audited);
  demo: todo's `creation_enabled`/`max_items_per_org` are now org-aware
- [ ] **user impersonation** (approved 2026-07-05, next up) — Pegasus ships it, Supabase dashboard has it; precious
  for support. Console action "view as user" with a visible banner + forced
  audit event on start/stop (the trail already exists). Time-boxed session,
  admin-gated.
- [x] **API keys** (approved 2026-07-05) — the JSON face of content negotiation currently only serves
  cookie sessions; machine integrations need `Authorization: Bearer <key>`.
  Per-org keys (owner-managed), hashed at rest, last-used tracking, revocation;
  a second auth dependency alongside `CurrentUser` resolving to the same
  org-scoped context so RLS still applies.
  → new `apps/api_keys/` context: owner-managed keys under /{org}/api-keys
  (sha256 at rest, secret shown once, throttled last-used, revocation);
  auth routes `Bearer lbk_...` through an `ApiKeyQuery` on the bus (no import),
  the principal is the key's creator pinned to the key's org; bearer GoTrue
  JWTs are accepted too as a side effect

### advanced auth

- [ ] @handle
- [ ] photo de profil
- [ ] disable / delete user
- [x] Forgot password (/auth/forgot-password + /auth/reset-password)
  → GoTrue recovery mail (custom `supabase/templates/recovery.html` carrying
  `token_hash` to our SSR route), `verify_otp` + stateless password update;
  E2E on both drivers reads the real mail from the catcher
- [x] Password change (authenticated) — POST /profile/password
  → re-authenticates with the current password via `auth.contract.passwords`,
  then GoTrue update; form on the profile page; audited
- [ ] Email change — POST /profile/email + SQL trigger to sync profiles.email
- [ ] Account deletion — DELETE /profile + cascade + logout
- [ ] Unconfirmed email verification — block login cleanly if email_confirmed_at is null
- [ ] Avatar — upload to Supabase Storage, the org_files pattern is directly reusable
- [ ] 2FA TOTP — Supabase Auth handles it natively, just wire up the UI flow
- [ ] OAuth social login (Google, GitHub) — callback page + merge with existing email account via auth.identities
- [ ] Passkeys / WebAuthn — auth.webauthn_credentials is already in the Supabase schema

## goals

### technical

- [ ] logs
- [ ] ETag on 
- [ ] COW, soft deletion, soft update
- [ ] async task queue
- [ ] fulltext index - elastic
  - recherche dans les pages
- [ ] documents - mango
- [ ] cache - redis
- [ ] messaging - kafka
- [ ] email
- [ ] prod deployment doc (secrets, env)
- [ ] https://12factor.net
- [ ] https://w.pitula.me/fintech-engineering-handbook/

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
