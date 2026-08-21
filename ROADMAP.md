> [!tip] An item listed here is not a debt, it is an opportunity.
> Nothing below is broken or promised. A line opens because it might be worth it — and closes
> just as well with "we're not doing this, delete the line" as with code. Replacing a brick that
> works with a brick that might work is a fair bet when the payoff is less code.


## issues

What misbehaves today. The first five come from a reading audit, each traced end to end (code,
Postgres roles, migrations, config); only their line references have moved since.

- [ ] The "one API key, one org" scope is a Python check, not an RLS policy — the key authenticates
  as its creator, and RLS alone would see every org of theirs. Handle-scoped routes are covered by
  `_ensure_api_key_scope`; the `{org_id}` + `require_owner` bypass is dormant. The real leak:
  `GET /organizations` enumerates every org its creator owns, and `POST /organizations` creates
  one. → a central gate on the collection routes whenever `api_key_org_id` is set.
  [context.py:61](apps/organizations/infra/context.py#L61),
  [router.py:168](apps/organizations/infra/router.py#L168),
  [router.py:210](apps/organizations/infra/router.py#L210)
- [ ] Switching `two_factor_enabled` off bypasses TOTP for everyone enrolled — `login` receives a
  full AAL1 session, the challenge only fires when the server-wide setting is true, and GoTrue does
  not backstop general AAL1 use. Deliberate: it is the admin kill-switch for a lost authenticator.
  The real flaw is granularity — global, all-or-nothing, flippable by any console admin. → a
  per-user reset rather than a server toggle. [router.py:233](apps/auth/infra/router.py#L233)
- [ ] Business-event redaction matches the field *name*, not its content — a denylist of fragments
  (`token|password|secret|apikey|otp|…`). Its scope has narrowed: `__init_subclass__` now refuses
  the field at class definition, and the write-path mask is only a net that logs at `error` when it
  fires. A secret named outside the fragments still gets through. Applies to `business_events`
  only, never to logs. → an allowlist. [types.py:63-88](apps/shared/events/types.py#L63),
  [repository.py:99](apps/shared/events/repository.py#L99)
- [ ] Template resolution is a sorted glob with no per-app namespace — first match wins,
  alphabetically. No real collision today (apps namespace themselves in a subdirectory); latent the
  day two apps drop a root `base.html`. → enforce the convention, or namespace the loader.
  [templates.py:33](apps/shared/http/templates.py#L33)
- [ ] A mistyped `"number"` setting silently falls back to `str` — `_coerce` calls `int(raw)` and
  returns the raw string on `ValueError`; `"1.5"` reads back as `str`, and decimals are
  unsupported. Unreachable today: no declared setting has a decimal default, and the write path
  rejects non-integers. [live.py:125](apps/shared/settings/live.py#L125)
- [ ] `home.html` ignores `current_user`: a signed-in user sees "Sign in" on an instance with no
  featured org. [router.py:37](apps/public/infra/router.py#L37)
- [ ] `/console/users`: the Accounts button and the "13 users" badge are inert.
- [ ] `MissingGreenlet` at the end of `make perf-smoke` — one connection, once per run, under load
  only. The chain: `_do_return_conn` → full pool → `_close_connection` → `asyncpg.close()` outside
  the greenlet, with no application frame at all, so it fires from a finaliser. Harmless, emitted
  by the process on its way out. Two leads ruled out (undisposed pools, a detached task collected
  in flight), each fixed without the trace moving. → `echo_pool` on one run, to read the real
  checkout/checkin sequence.


## features

- [ ] The console should show a dedicated growth activity report — the sign-ups chart exists on the
  overview, the screen does not.
- [ ] `/console/organizations` should list organisations and give metrics.
- [ ] AARRR metrics
- [ ] Product tour
- [ ] Awareness, `@citation`, notification
- [ ] ApexCharts heatmap → https://apexcharts.com/javascript-chart-demos/heatmap-charts/basic/


## technical opportunities

The first ones have their diagnosis done and their remedy named; the rest are still questions.

- [ ] The correlation triplet crosses the timeline↔issues contract as loose kwargs.
  `_issue_kwargs` starts from `_event_kwargs` then `del`s two keys to land on the seven named
  parameters of `search_issue_occurrences`. `TimelineFilter` already *is* that object on the caller
  side: it is flattened, then re-narrowed per source. Adding a filter costs the dataclass,
  `_event_kwargs`, three `del` lists and every contract signature; a `del` on a key the other query
  no longer has is a runtime `KeyError`, not a type error. → a frozen `OccurrenceFilter` in the
  contract, built explicitly by the timeline.
  [repository.py:283](apps/timeline/infra/repository.py#L283),
  [queries.py:32](apps/issues/contract/queries.py#L32)
- [ ] `issue_occurrences` correlates inside the JSONB with no index to serve it — filters on
  `context['org_id'].astext` (same for user_id, request_id) and an `ilike` on
  `cast(context as text)`, against a single `(issue_id, id desc)` index. Every correlated Timeline
  read scans sequentially, and only retention purging bounds the volume. The columns exist on
  `business_events` — issues chose JSONB. → promote the three correlation keys to real columns,
  migration + backfill. [20260818000007_issues.sql:49](supabase/migrations/20260818000007_issues.sql#L49)
- [ ] 29 README sentences nothing proves. `UNHELD_TODAY` is the most honest backlog in the repo:
  every waived claim names what would have to be built to hold it. The number only goes down by a
  decision. [claims.py:582](tests/meta/claims.py#L582)
- [ ] `AppManifest` covers 6 apps out of 16 — the other ten re-spell the mount ceremony by hand.
  That is exactly the `integration-is-declarative` claim that stays unproven.
  [host.py:80](apps/shared/integration/host.py#L80)
- [ ] Fewer `str`, more types — starting with settings: `SettingsView.__getattr__` returns `Any`,
  so `TodoSettings`, `PublicSettings` and the rest are the same untyped object under different
  names. Hence the three `# type: ignore[assignment]` on `featured_org_handle`, the only ones in
  application code. This is the hole in "invariants are types, not checks".
  [live.py:172](apps/shared/settings/live.py#L172)
- [ ] Route the API-key path through the app's own Storage credentials, keeping the org pin as the
  single source of the path. An API-key principal carries `access_token = ""`, so
  `user_storage_client()` has nothing to present. The precedent already exists: avatar upload goes
  through `admin_storage()` for an authenticated user.
- [ ] Hunt the N+1s — the instrumentation now exists (`db.heavy_request` writes a line as soon as a
  request crosses its query-count or SQL-time threshold); what is left is opening what it reports.
- [ ] DB indexes → `index_advisor` + `hypopg` (see extensions)
- [ ] `_ENTITY_ROUTES` in `apps/organizations` is a coupling — an app is named there to earn a deep
  link. [entity_links.py:18](apps/organizations/contract/entity_links.py#L18)
- [ ] Should `jinja_globals` live in the host?
- [ ] Reduce the `| None = None` — 199 occurrences under `apps/`.
- [ ] Split the SQLAlchemy models (`domain`) from the Pydantic models (`contract`), in every app.
- [ ] `_ACTIVITY_PAGE` and the other pagination constants should become settings.
- [ ] `todo_completion_stats` → a real-time count, generalisable to every app.
- [ ] Role-Based Access Control — `owner`/`member` is binary.
- [ ] Named permissions — a permission model beyond binary roles, worth keeping in mind for the
  first client contract asking for custom roles.
- [ ] Dataclass or Pydantic?
- [ ] Multi-process? One Hypercorn today, and five background loops per process.
- [ ] Command Query Responsibility Segregation?
- [ ] Use SQLAlchemy more the way JPA is used
- [ ] COW, soft deletion, soft update
- [ ] Better styleguide, inspired by my apps and the daisyUI templates.
- [ ] Fulltext search in pages → Postgres FTS or `vector` (see extensions)
- [ ] Documents → `pg_jsonschema` (see extensions)
- [ ] Messaging → `pgmq` (see extensions)
- [ ] Cache
- [ ] Email — the `Mailer` port exists; deliverability is a production-readiness item.
- [ ] GDPR export
- [ ] CLI
- [ ] MCP server?
- [ ] i18n — every UI string is hardcoded English. Jinja2 route: Babel/gettext extraction,
  per-request locale (cookie or `Accept-Language`), catalogues per context. Expensive to retrofit.
  → consciously deferred (2026-07-05).
- [ ] Billing — the one link entirely missing from the grammar of a credible SaaS kit
  (auth + teams + billing + email + jobs). Shape: a `billing/` bounded context, standard mount,
  subscription per org managed by the owner, Stripe Checkout + customer portal (no card UI to
  build), a webhook feeding typed events (`SubscriptionChanged`) onto the bus, plan gates readable
  by other apps the way declared settings are, an MRR stat on the console. Domain kept
  vendor-agnostic behind a port, Stripe adapter first. → out of scope (2026-07-05).
  https://github.com/t3dotgg/stripe-recommendations
- [ ] https://12factor.net
- [ ] https://w.pitula.me/fintech-engineering-handbook/
- [ ] https://datacater.io/blog/2021-09-02/postgresql-cdc-complete-guide.html


### production readiness

Going from "it runs on my machine" to "shippable and operable". Already in place, not to be
rebuilt — four-layer observability, `health/` probes, cross-instance rate limiting, RLS, security
headers, `Sec-Fetch-Site` CSRF, backup docs. The gap is not the runtime, it is the path to
production and its operation. Full runbook in [production.md](docs/production.md).

Ordered: the first line stands between the base and a first client deployment, the last is polish
once it is running.

- [ ] The preflight's `len(SUPABASE_SECRET_KEY) < 40` threshold is a heuristic that refuses boot
  with no way out. Measured: a real `sb_secret_…` key is 41 characters — a one-character margin.
  Legacy `service_role` keys are very long JWTs and sail through. A false positive locks production
  out. → validate a prefix rather than a length, or downgrade to a warning.
  [preflight.py](apps/shared/settings/preflight.py)
- [ ] Deployment CI/CD — a pipeline gated on `make ci`, an image tagged by version (`apps/issues`
  already tracks regression by version), migration, rollback.
- [ ] Alerting — the issue half is done: `issues.alerting_enabled` + `alert_email` send mail on an
  issue opening or regressing, as a durable consumer. What remains is parked tasks in the queue,
  load thresholds (`/metrics` exists) and readiness failures. Prometheus scrape + Grafana dashboard.
- [ ] Log shipping — structured JSON out to an aggregator (Loki, CloudWatch…). Overlaps Supabase
  Log Drains.
- [ ] Image scan + CI secret scan — Trivy on the image; talisman, already in pre-commit, promoted
  to a blocking CI gate.
- [ ] Email deliverability — a real provider behind the `Mailer` port, plus SPF/DKIM/DMARC.
- [ ] Uptime monitoring — an external synthetic check on readiness.
- [ ] Explicit timeouts on every outbound call (Supabase, SMTP) — the queue already has its backoff.
- [ ] Harden the CSP — tighten `script-src` / `connect-src` now that the front end is stable.
- [ ] Automated restore drill, and written RTO/RPO targets — the drill is documented, not
  continuously tested.
- [ ] Runbooks — deploy, incident, on-call; SLO and error-budget doc.
- [ ] Horizontal scaling guide — the `TaskWorker` is already multi-instance safe; document
  pooler/worker sizing and a load test beyond `perf-smoke`.


## possible Supabase integrations

The platform catalogue, reread 2026-08-21. A ticked line is in use; an annotated line carries a
decision already taken. Capabilities shipped as Postgres extensions are in the next list, which is
where the most is left to gain.

- [ ] AI Integrations - Enhance applications with OpenAI and Hugging Face integrations.
- [ ] Auth Hooks - Customize authentication flows with serverless functions.
- [x] Authorization via Row Level Security - the source of truth for isolation, in versioned SQL.
- [ ] Auto-generated GraphQL API via pg_graphql - see extensions.
- [~] Auto-generated REST API via PostgREST - reached indirectly through `supabase-py` (admin,
  Storage, GoTrue); business routes are hand-written, each with two faces.
- [ ] Automatic Embeddings - Automated embedding generation using triggers and queues.
- [x] CLI - versioned SQL migrations, local stack, `make db-reset`.
- [ ] Captcha protection - Add Captcha to your sign-in, sign-up, and password reset forms.
- [x] Client Library - Python - `supabase-py`, JWT in an HTTPOnly cookie.
- [ ] Content Delivery Network - Cache large files using the Supabase CDN.
- [~] Cron - replaced by the queue's recurring re-enqueue; see `pg_cron` under extensions.
- [ ] Custom Identity Providers - Connect any OAuth2 or OIDC identity provider to Supabase Auth.
- [ ] Database Webhooks - Trigger external payloads on database events.
- [x] Database backups - daily + PITR on the platform side; coverage and drill in
  [backups.md](docs/backups.md).
- [ ] Declarative Schemas - the fifteen migrations are hand-written, in dependency order.
- [ ] Dedicated Poolers - Co-located connection pooler for maximum performance.
- [ ] Deno Edge Functions - Globally distributed TypeScript functions to execute custom business logic.
- [ ] Functions
- [x] Email Templates - `recovery`, `email_change` and `confirmation` point at the app's own SSR
  routes.
- [x] Email login - with mailed confirmation, resend on a blocked sign-in, forgot/reset flow.
- [x] File storage - org-scoped buckets, immutable share tokens for anonymous download.
- [ ] Foreign Data Wrappers - see extensions.
- [ ] Foreign Key Selector - Easily manage foreign key relationships between tables.
- [ ] Image transformations - Optimize and resize images on-the-fly directly from your Supabase storage buckets.
- [ ] JWT Signing Keys - Asymmetric key management for enhanced JWT security.
- [ ] Log Drains - the app writes its own shared `log_lines`; the external export is the "log
  shipping" item under production readiness.
- [ ] Logs & Analytics - the console Timeline reads the journal, the log sink and issue occurrences.
- [x] Multi-Factor Authentication (MFA) - GoTrue TOTP factors, enrolment on the profile and step-up
  at sign-in, behind a console switch.
- [ ] Network restrictions - Restrict IP ranges that can connect to your database.
- [ ] OAuth2.1 Server - Turn your project into an OAuth 2.1 identity provider.
- [ ] Passwordless login via Magic Links - Build passwordless logins via magic links.
- [x] Passkeys (WebAuthn) - GoTrue ceremonies, `rp_origins` covering the e2e servers; console
  switch, off by default.
- [ ] Persistent Storage - Mount S3 buckets for 97% faster Edge Function cold starts.
- [ ] Phone logins - Provide phone logins using a third-party SMS provider.
- [ ] Policy Templates - Quickly implement common security policies.
- [ ] Postgres Extensions - see the next list.
- [x] Postgres Roles - every migration grants explicitly to `authenticated` and `service_role`.
- [x] Postgres database - RANGE partitions, `UNLOGGED`, triggers, `SECURITY DEFINER`,
  `FOR UPDATE SKIP LOCKED`, `LISTEN`/`NOTIFY`.
- [ ] Broadcast - Send messages between connected users through websockets.
- [ ] Broadcast Authorization - Control access to broadcast channels in real-time.
- [ ] Broadcast from the Database - Trigger broadcast messages directly from Postgres.
- [~] Postgres changes - the event listener reads the journal, woken by `NOTIFY`, with polling as a
  net. Realtime is excluded from the local stack and from CI.
- [ ] Presence - Synchronize shared state between users through websockets.
- [ ] Presence Authorization - Manage presence information securely in real-time.
- [ ] Reports & Metrics - `apps/metrics` counts, exposes `/metrics` and renders the Load screen.
- [ ] Resumable uploads - Upload large files using resumable uploads.
- [ ] S3 compatibility - Interact with Storage from tools which support the S3 protocol.
- [x] SQL Editor - Studio, linked from every console settings page (`SupabaseLink`).
- [ ] SSL enforcement - Enforce secure connections to your Postgres clients.
- [ ] SSO with SAML - Enterprise single sign-on using SAML protocol.
- [ ] Security & Performance Advisor - Optimize your database security and performance effortlessly.
- [x] Server-side Auth - server rendering, JWT in an HTTPOnly cookie, never exposed to the browser.
- [ ] Smart Content Delivery Network - Automatically revalidate assets at the edge via the Smart CDN.
- [x] Social login - Google and GitHub over PKCE, each behind its own console switch.
- [ ] Supavisor - the pooler expected in production; sizing to document (see production readiness).
- [ ] Third-Party Authentication - Trust JWTs from external authentication providers.
- [ ] User Impersonation - the app has its own, bannered and recorded; Supabase's tests policies in
  Studio, which is not the same thing.
- [ ] Vector Database - see extensions.
- [ ] Visual Schema Designer - Design your Postgres database schema with an intuitive interface.
- [ ] Web3 Authentication - Wallet-based authentication for Ethereum and Solana.


## possible extensions integrations

`pg_available_extensions` on the local stack — the half the catalogue above cannot show, and the
one where three hand-written bricks double an extension already provisioned. The stack runs
PostgreSQL 17.6: the hand-rolled `uuidv7()` is correct today and becomes dead weight the day
Supabase moves to 18, where it is native.

Installed:

- [x] `pgcrypto` 1.3 — `gen_random_uuid()`, the entropy behind security tokens.
- [ ] `pg_net` 0.20.4 — provisioned by Supabase, unused.
- [ ] `pg_stat_statements` 1.11 — provisioned, unused. Doubles the hand-written SQL tally feeding
  `db.heavy_request`. [sql_stats.py](apps/shared/persistence/sql_stats.py)

Available:

- [ ] `index_advisor` 0.2.0 + `hypopg` 1.4.1 — the cheapest win on the list: no coupling at all,
  installed for the length of a session, and it answers "DB indexes?" and the missing
  `issue_occurrences` index directly.
- [ ] `pg_partman` 5.3.1 — would replace `roll_log_partitions`, the hand-written SQL function that
  creates `log_lines`' daily partitions and applies retention. Rolling partitions is not a design
  choice, it is maintenance.
  [20260818000015_log_lines.sql:90](supabase/migrations/20260818000015_log_lines.sql#L90)
- [ ] `pgmq` 1.5.1 — Supabase's message queue: table, visibility timeout, archive. Covers
  `apps/shared/queue.py` (324 lines) almost line for line. What `pgmq` does not carry, and what is
  the doctrine, is the outbox semantics — they hold because `enqueue()` writes through *the
  caller's session*. The bet: less code, against a brick whose every line the README can no longer
  explain. [queue.py](apps/shared/queue.py)
- [ ] `pg_cron` 1.6.4 — would replace the wake-up of purges and rollups, today a re-enqueue in
  Python. It does not replace the queue, only the scheduling: still open whether splitting the
  recurring half in two is a simplification or one more seam. [queue.py:109](apps/shared/queue.py#L109)
- [ ] `vector` 0.8.2 — semantic search. To decide alongside Postgres FTS, which answers half of
  "search in pages" with no extension at all.
- [ ] `pg_jsonschema` 0.3.3 — would validate the JSONB columns in the database (fact payloads,
  occurrence context), where only Python constrains the shape today.
- [ ] `pg_graphql` 1.6.1 — a second generated face for the API. To weigh against the two-faces
  doctrine, which already makes every route readable as JSON.
- [ ] `postgres_fdw` 1.1 / `wrappers` 0.6.2 — read an external source as a Postgres table.
- [ ] `http` 1.6 — outbound calls from the database. Overlaps `pg_net`, already installed.
- [ ] `pgsodium` 3.1.8 — per-column encryption at rest.
