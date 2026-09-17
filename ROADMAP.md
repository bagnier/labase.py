> [!tip] An item listed here is not a debt, it is an opportunity.
> Nothing below is broken or promised. A line opens because it might be worth it — and closes
> just as well with "we're not doing this, delete the line" as with code. Replacing a brick that
> works with a brick that might work is a fair bet when the payoff is less code.


## issues

- [ ] The "one API key, one org" scope is a Python check, not an RLS policy — the key authenticates
  as its creator, and RLS alone would see every org of theirs. Handle-scoped routes are covered by
  `_ensure_api_key_scope`; the `{org_id}` + `require_owner` bypass is dormant. The real leak:
  `GET /organizations` enumerates every org its creator owns, and `POST /organizations` creates
  one. → a central gate on the collection routes whenever `api_key_org_id` is set.
  [context.py:61](apps/organizations/infra/context.py#L61),
  [router.py:168](apps/organizations/infra/router.py#L168),
  [router.py:210](apps/organizations/infra/router.py#L210)
- [ ] `home.html` ignores `current_user`: a signed-in user sees "Sign in" on an instance with no
  featured org. [router.py:37](apps/public/infra/router.py#L37)

- [ ] 29 README sentences nothing proves. `UNHELD_TODAY` is the most honest backlog in the repo:
  every waived claim names what would have to be built to hold it. [claims.py:582](tests/meta/claims.py#L582)
- [ ] The files browser scenarios are intermittent: `make flakehunt N=5` on them failed 2 runs out
  of 5 (2026-09-15), each a 30 s wait for the HTMX response of a row button — delete once, share
  twice. Not dated: never compared against the tree before the dependency upgrade. → `flakehunt`
  on that commit to date it, then whether the request leaves at all.
  [browser_base.py:352](tests/e2e/drivers/browser_base.py#L352),
  [driver_mixin_browser.py:122](apps/files/tests/e2e/driver_mixin_browser.py#L122),
  [driver_mixin_browser.py:235](apps/files/tests/e2e/driver_mixin_browser.py#L235)
- [ ] Two runs in the same checkout break each other: they share its test stack and its `test`
  schema, which `make test` drops and rebuilds (`provision-test`) and the browser driver truncates
  between scenarios. → one schema per run.
  [provision_schema.py:189](scripts/provision_schema.py#L189), [cleanup.py:71](tests/e2e/cleanup.py#L71)
- [ ] `make backup-storage` stops at 100 objects per folder and reports success: `store.list()` is
  called without options, and `storage3` sends a default page of 100. On the dev stack, 100 of
  1736 objects. → page with `limit`/`offset`. [backup_storage.py:26](scripts/backup_storage.py#L26)
- [ ] Avatars live in the `org-files` bucket under `avatars/`, a first segment every storage policy
  casts to a uuid: once one exists, any user-scoped listing of the bucket raises. The app never
  lists with a user token, so nothing fails today. → a bucket of their own, or a prefix the
  policies skip. [router.py:631](apps/profile/infra/router.py#L631)
- [ ] Nothing in `config.toml` reaches a hosted project — no `supabase config push` anywhere. A
  hosted project mails GoTrue's default templates, whose links carry no `token_hash` for the
  reset route, and keeps its own email quota. → push the config from the deploy path.
- [ ] Sign-in and sign-up reach GoTrue from the server without the client's address, so GoTrue's
  per-IP limit sees one caller per instance: when the app's limiter fails open, nothing limits a
  single caller. → forward the client IP, or accept the limiter as the only floor.
  [service.py:44](apps/auth/domain/service.py#L44)


## features

- [ ] The console should show a dedicated growth activity report — the sign-ups chart exists on the
  overview, the screen does not.
- [ ] `/console/organizations` should list organisations and give metrics.
- [ ] AARRR metrics
- [ ] Product tour
- [ ] Role-Based Access Control, Named permissions — `owner`/`member` is binary.
- [ ] Awareness, `@citation`, notification
- [ ] ApexCharts heatmap → https://apexcharts.com/javascript-chart-demos/heatmap-charts/basic/


## technical opportunities

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
- [ ] `_ENTITY_ROUTES` in `apps/organizations` is a coupling — an app is named there to earn a deep
  link. [entity_links.py:18](apps/organizations/contract/entity_links.py#L18)
- [ ] Should `jinja_globals` live in the host?
- [ ] Split the SQLAlchemy models (`domain`) from the Pydantic models (`contract`), in every app.
- [ ] `_ACTIVITY_PAGE` and the other pagination constants should become settings.
- [ ] `todo_completion_stats` → a real-time count, generalisable to every app.
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
rebuilt — observability, `health/` probes, cross-instance rate limiting, RLS, security
headers, `Sec-Fetch-Site` CSRF, backup docs. The gap is not the runtime, it is the path to
production and its operation. Full runbook in [production.md](docs/production.md).

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
- [~] Horizontal scaling guide — the `TaskWorker` is already multi-instance safe; document
  pooler/worker sizing and a load test beyond `perf-smoke`.
- [ ] production.md routes both database URLs through Supavisor in transaction mode, which supports
  neither `LISTEN` — the event listener's wake-up would fall to polling, silently — nor the
  prepared statements asyncpg caches. → session mode or a direct connection, and say which.
  [listener.py:226](apps/shared/events/listener.py#L226), [production.md](docs/production.md)


## possible Supabase integrations

Every entry of supabase.com/features, name and wording as the page carries them, reread against the
tree 2026-09-17. `[x]` is in use, `[~]` partly. `[?]` is for a seam this tree really has and the
feature really answers, with the question still open, and the line says when a paid plan gates it.
`[ ]` is everything else — no seam, or a decision already taken, which the line then names. An
entry that is a Postgres extension, or is built on one, defers to the next list, which is where the
most is left to gain.

- [ ] AI Integrations - Enhance applications with OpenAI and Hugging Face integrations. Follows
  `vector` in the next list.
- [ ] Analytics Buckets (with Iceberg) - Large-scale analytics using Apache Iceberg format.
- [?] Auth Hooks - Customize authentication flows with serverless functions. → an access token hook
  would stamp org membership into the JWT, which most policies re-read through a SECURITY DEFINER
  helper on each query; the per-user and public-read ones have no membership to stamp. The hook is
  itself a Postgres function, and the free plan has it. Against it: a claim stale until the
  refresh, and two paths that never see a GoTrue token — queue tasks and API keys build their own
  claims, so a policy reading the stamp would deny both.
- [x] Authorization via Row Level Security - Control the data each user can access with Postgres
  Policies. The source of truth for isolation, in versioned SQL — except `org_file_share_tokens`,
  which has RLS off by design, the token being the gate.
- [ ] Auto-generated GraphQL API via pg_graphql - Fast GraphQL APIs using our custom Postgres
  GraphQL extension. See extensions.
- [~] Auto-generated REST API via PostgREST - RESTful APIs auto-generated from your database. No call
  site of ours: data goes through asyncpg + SQLAlchemy, Storage through `storage3`, and business
  routes are hand-written, each with two faces. It is served all the same, to anyone holding the
  publishable key: `anon`, a role the app never connects as, gets every right Supabase's default
  privileges grant on a new table or function in `public`, and no migration revokes them.
- [ ] Automatic Embeddings - Automated embedding generation using triggers and queues. Built on
  `vector`, `pgmq`, `pg_net` and `pg_cron`, all four in the next list.
- [?] Branching - Test schema changes without touching production. → `make worktree` already gives
  each checkout its own schema, bucket and test stack, locally. Branching is the same idea on the
  remote, which is what the deployment pipeline under production readiness would need. Pro,
  billed per branch-hour.
- [x] CLI - Use our CLI to develop your project locally and deploy. Versioned SQL migrations, local
  stack, `make db-reset`, one test stack per checkout — and nothing else of `config.toml` ever
  reaches a remote: there is no `supabase config push`.
- [?] Captcha protection - Add Captcha to your sign-in, sign-up, and password reset forms. → those
  three are rate-limited per IP by a limiter that fails open by design, and it is the only per-caller
  limit there is: the app calls GoTrue from the server without forwarding the client's address, so
  GoTrue's own per-IP counter sees one caller per instance.
- [ ] Client Library - Flutter - Integrate Supabase into your Flutter applications effortlessly.
- [ ] Client Library - JavaScript - Easily integrate Supabase with your JavaScript applications.
  The browser never holds a token: the JWT stays in an HTTPOnly cookie, so nothing there could
  authenticate a call.
- [x] Client Library - Python - Integrate Supabase easily into your Python applications.
  `supabase-py` for auth and its `storage3` package for Storage, the JWT in an HTTPOnly cookie.
- [ ] Client Library - Swift - Effortlessly connect your Swift applications to Supabase.
- [?] Content Delivery Network - Cache large files using the Supabase CDN. → downloads redirect to
  a Storage origin already, but both handlers mint a fresh signed URL per request, and a new token
  is a new cache key — the cache never warms. Every plan has the basic CDN; caching signed URLs is
  the Smart CDN, from Pro. Reusing a URL is the work, and its cost: a cached entry outlives the
  token that minted it, so an expired share or a removed member keeps access until the object goes.
- [ ] Cron - Schedule recurring Jobs in Postgres. Recurring work re-enqueues itself from Python;
  Supabase Cron is `pg_cron`, so the trade is argued in the next list.
- [?] Custom Identity Providers - Connect any OAuth2 or OIDC identity provider to Supabase Auth.
  → the PKCE round-trip is provider-agnostic and already carries Google and GitHub. Adding one
  means extending the `OAUTH_PROVIDERS` constant, declaring its switch, and teaching the template a
  third icon. Three custom providers on the free plan, unlimited from Pro.
- [?] Custom domains - White-label the Supabase APIs for a branded experience. → during an OAuth
  sign-in the browser is sent to the project's own Supabase domain. The tree needs nothing to
  change it — `SUPABASE_API_URL` is one value, and Storage follows it — so the whole cost is the
  add-on, from Pro.
- [ ] Database Webhooks - Trigger external payloads on database events. Built on `pg_net`, in the
  next list; the in-tree counterpart is the event listener's fan-out off `business_events`.
- [~] Database backups - Projects are backed up daily with Point in Time recovery options. The choice
  is made — [backups.md](docs/backups.md) buys the platform's, from Pro, with PITR as a paid add-on —
  and the tree carries the other half: a restore drill, and `make backup-storage` for the bytes no
  SQL dump holds. Nothing runs either until a hosted project exists.
- [ ] Declarative Schemas - Simplify database management with declarative schema files. Migrations
  are plain SQL written in dependency order, by choice: the README's stack table picks the CLI's
  versioned migrations for full control, and `log_lines` creates its partitions from dynamic SQL,
  which no schema file describes.
- [?] Dedicated Poolers - Co-located connection pooler for maximum performance. → the same question
  as Supavisor below, answered on a paid plan: Supabase points a backend that can reach it at the
  dedicated pooler rather than the shared one.
- [ ] Deno Edge Functions - Globally distributed TypeScript functions to execute custom business
  logic. Nothing here needs code outside the request path or the queue, and a second runtime is a
  second place for business logic to live.
- [~] Email Templates - Customizable email templates for all authentication flows. `recovery`,
  `email_change` and `confirmation` point at the app's own SSR routes — on local stacks only. They
  live in `config.toml`, which nothing pushes, so a hosted project mails GoTrue's defaults and the
  reset route never receives its `token_hash`.
- [x] Email login - Build email logins for your application or website. Forgot/reset flow, and the
  mailed-confirmation path with its resend on a blocked sign-in — built, but `enable_confirmations`
  is off in `config.toml`, so every local stack auto-confirms and the scenario builds its
  unconfirmed user through the admin API.
- [x] File storage - Supabase Storage makes it simple to store and serve files. One bucket per
  deployment, isolated per org by RLS on the first path segment, and immutable share tokens for
  anonymous download. Avatars share the bucket under `avatars/`, a segment the policies cast to a
  uuid: once one exists, any user-scoped listing of the bucket fails. The app never lists that way.
- [ ] Foreign Data Wrappers - Query external data sources as Postgres tables. See extensions.
- [ ] Foreign Key Selector - Easily manage foreign key relationships between tables. The schema is
  authored in SQL migrations, never in Studio.
- [?] Image transformations - Optimize and resize images on-the-fly directly from your Supabase
  storage buckets. → an avatar is downloaded whole through the app and streamed back at upload
  size, cached five minutes per browser. Locally it takes a `[storage.image_transformation]` block
  in `config.toml` and `imgproxy` out of the test stack's exclusions; hosted, it is Pro and
  metered.
- [x] JWT Signing Keys - Asymmetric key management for enhanced JWT security. The app verifies
  RS256/ES256 against the project JWKS, so no shared signing secret ever reaches the process.
- [?] Log Drains - Export logs to Datadog, Grafana, Sentry, S3, and more — now available on Pro.
  → the app writes its own shared `log_lines`; Postgres, GoTrue and Storage keep theirs on the
  platform. The app sees a GoTrue or Storage failure from its side — an error line and an issue —
  but never why, and a Postgres outage takes the Timeline down with it. Answers the "log shipping"
  readiness item from the other side.
- [?] Logs & Analytics - Gain insights into your application’s performance and usage. → the same
  seam as Log Drains: the console Timeline is app-side by construction.
- [ ] MCP Server - Connect your AI tools using the official Supabase Model Context Protocol (MCP)
  server. Not in `.mcp.json`, and not what the "MCP server?" line above asks for, which is one of
  our own.
- [?] Management API - Manage your projects programmatically. → its logs endpoint returns every
  service's lines for the last day, on the free plan's retention — the Timeline could read
  GoTrue's and Storage's side of a failure without a drain.
- [x] Multi-Factor Authentication (MFA) - Add an extra layer of security to your application with
  MFA. GoTrue TOTP factors, enrolment on the profile and step-up at sign-in, behind a console switch.
- [?] Network restrictions - Restrict IP ranges that can connect to your database. → absent from
  production.md, and scriptable through the CLI. It guards the two database URLs, whose passwords
  can reach Postgres from anywhere today; it does nothing for a leaked secret key, which reaches the
  project through its HTTP APIs.
- [?] OAuth2.1 Server - Turn your project into an OAuth 2.1 identity provider. → `api_keys` already
  issues per-org `lbk_…` bearer tokens; an OAuth server is what the "MCP server?" line above needs
  to be more than a personal token. Free plan.
- [ ] OrioleDB - New Postgres storage engine that's better than Heap storage.
- [?] Passwordless login via Magic Links - Build passwordless logins via magic links for your
  application or website. → most of it exists: impersonation already confirms a `magiclink` token,
  and `/auth/confirm` takes any token type and records the sign-in. Missing: the `magic_link`
  template, a sign-in form and a console switch.
- [ ] Persistent Storage - Mount S3 buckets for 97% faster Edge Function cold starts. Follows Deno
  Edge Functions.
- [ ] Phone logins - Provide phone logins using a third-party SMS provider.
- [ ] Policy Templates - Quickly implement common security policies. Policies are written in
  migrations, never in Studio — the org-isolation shape the templates offer is the one the
  SECURITY DEFINER helpers already implement.
- [ ] Postgres Extensions - Enhance your database with popular Postgres extensions. Nothing in the
  tree calls one: `gen_random_uuid()` is core on PG 17, and `uuidv7()` is pure core SQL on purpose.
  See the next list.
- [x] Postgres Roles - Managing access to your Postgres database and configuring permissions. The app
  logs in as its own role and pins `authenticated` per transaction, never from the token; admin
  work runs as `postgres`. Grants are explicit in every migration, but additive: Supabase's default
  privileges already give `anon` and `authenticated` every right on a new table or function in
  `public`, and a `revoke … from public` does not remove them.
- [x] Postgres database - Every project is a full Postgres database. RANGE partitions, `UNLOGGED`,
  triggers, `SECURITY DEFINER`, `FOR UPDATE SKIP LOCKED`, `LISTEN`/`NOTIFY`.
- [ ] PrivateLink - Secure private network connectivity to your Supabase database.
- [ ] Queues - Durable messages with guaranteed delivery. `apps/shared/queue.py` is this,
  hand-written; Supabase Queues is `pgmq`, argued in the next list.
- [ ] Read replicas - Isolate heavy workloads and reduce global latency. There is no read-only
  engine to point at one: the console's reads go to the primary with everything else.
- [?] Realtime - Broadcast - Send messages between connected users through websockets. →
  `live_refresh` polls every 30 s on the Timeline and the Tasks history. Both are admin screens, and
  a private channel needs a token the browser never holds, so a channel means a server-side relay
  too — plus Realtime in the test stack, which drops it.
- [ ] Realtime - Broadcast Authorization - Control access to broadcast channels in real-time.
  Follows Broadcast.
- [ ] Realtime - Broadcast Replay - Access previously sent messages in private channels. Follows
  Broadcast.
- [ ] Realtime - Broadcast from the Database - Trigger broadcast messages directly from Postgres.
  Follows Broadcast.
- [ ] Realtime - Postgres changes - Receive your database changes through websockets. The event
  listener reads the journal itself, woken by `LISTEN`/`NOTIFY` on a direct connection and by
  polling otherwise; Realtime runs unused on the dev stack and is dropped from the test stack.
- [ ] Realtime - Presence - Synchronize shared state between users through websockets. No surface
  shows who else is here; waits on Broadcast and on the "Awareness, `@citation`, notification"
  feature above.
- [ ] Realtime - Presence Authorization - Manage presence information securely in real-time.
  Follows Presence.
- [ ] Regional invocations - Execute an Edge Function in a region close to your database. Follows
  Deno Edge Functions.
- [?] Reports & Metrics - Monitor your project's health with usage insights. → `apps/metrics`
  counts, exposes `/metrics` and renders the Load screen. Connections and cache hit rate are in
  `pg_stat_database`, size in `pg_database_size()`, both on the session the Load screen already
  opens; what only Supabase has is host-side — CPU, memory, disk I/O — through a metrics endpoint
  that starts at Pro.
- [?] Resumable uploads - Upload large files using resumable uploads. → the upload is read whole
  into the process, and only then compared to `max_upload_mb`, so the setting bounds what is kept,
  not what is read. Resuming the app-to-Storage leg would not change that; a signed upload URL,
  which the browser uses directly with no JWT, would.
- [?] Role-Based Access Control (RBAC) - Define and manage user roles securely → exactly the
  "Role-Based Access Control, Named permissions" feature above: `owner`/`member` is binary, and
  most policies only ask membership, never the role. A third role lives outside RLS altogether:
  the server admin, read from `app_metadata` and checked in Python on BYPASSRLS sessions.
  Supabase's pattern stamps the role through a custom access token hook, with the two blind paths
  the Auth Hooks line names.
- [ ] S3 compatibility - Interact with Storage from tools which support the S3 protocol. Nothing
  here needs it: the backup script already holds a key with full Storage access, and the S3 keys
  would be one more secret with the same reach.
- [ ] SOC 2 Compliance - Build with confidence on a SOC 2 compliant platform. A property of the
  platform, from the Team plan, not something to integrate.
- [ ] SQL Editor - A powerful interface for writing and executing SQL queries. Studio is deep-linked
  from each app's console page (`SupabaseLink`), but at the table editor, the Auth users list or the
  Storage bucket — never the SQL editor, and `supabase/snippets/` is empty.
- [?] SSL enforcement - Enforce secure connections to your Postgres clients. → absent from
  production.md, and reachable from the deploy path through the same CLI that runs
  `supabase db push`. No production connection string here states an `sslmode`; the two that do
  are the local `tbls` configs, set to `disable`.
- [?] SSO with SAML - Enterprise single sign-on using SAML protocol. → the same seam as Custom
  Identity Providers, with an org handle already there to map a tenant's domain to its provider;
  the installed client has `sign_in_with_sso`. Pro, billed per MAU past 50.
- [?] Security & Performance Advisor - Optimize your database security and performance
  effortlessly. → its lints run against the local stack already, through Studio, and nothing here
  reads them. On this schema they report errors, not only warnings — a public table with RLS off,
  a token column exposed — and they propose indexes for the unindexed foreign keys.
- [?] Server-side Auth - Helpers for implementing user authentication in popular server-side
  languages. → sign-in, sign-up and refresh already go through `supabase-py`, but the OAuth PKCE
  pair and the code exchange are hand-rolled over `httpx`, where the installed client has a
  `pkce` flow and `exchange_code_for_session`.
- [?] Smart Content Delivery Network - Automatically revalidate assets at the edge via the Smart
  CDN. → the Storage CDN itself from Pro, and the one that caches signed URLs — so the seam, the
  work and the revocation cost of Content Delivery Network.
- [x] Social login - Provide social logins from platforms like Apple, GitHub, and Slack. Google and
  GitHub over PKCE, each behind its own console switch.
- [ ] Supabase AI Assistant - Your intelligent companion for managing Postgres databases.
- [ ] Supabase Pipelines - Replicate Postgres data to analytical destinations.
- [?] Supavisor - A scalable connection pooler for Postgres. → production.md routes both database
  URLs through it in transaction mode, which supports neither prepared statements, which asyncpg
  caches, nor `LISTEN`, on which the event listener waits. Session mode, or a direct connection,
  is the open choice.
- [?] Terraform provider - Manage Supabase infrastructure via Terraform. → the project's settings
  live nowhere in the repo, and the provider's `supabase_settings` carries most of what this list
  touches: SSL enforcement, network restrictions, the pooler, auth hooks, captcha, OAuth secrets,
  SMTP, image transformation, the S3 protocol. Custom domains and log drains have no resource.
- [ ] Third-Party Authentication - Trust JWTs from external authentication providers. GoTrue is the
  only issuer the app trusts; OAuth2.1 Server is the direction worth having.
- [ ] User Impersonation - Experience your application as any user. The app has its own, bannered
  and recorded; Supabase's tests policies in Studio, which is not the same thing.
- [ ] Vault - Manage secrets safely in Postgres. It is `supabase_vault`, argued in the next list.
- [ ] Vector Buckets - S3-backed storage for vector embeddings with similarity search. Follows
  Vector database.
- [ ] Vector database - Store vector embeddings right next to the rest of your data. It is
  `vector`, argued in the next list.
- [ ] Visual Schema Designer - Design your Postgres database schema with an intuitive interface.
  See Foreign Key Selector.
- [ ] Web3 Authentication - Wallet-based authentication for Ethereum and Solana.


## possible extensions integrations

`pg_available_extensions` on the local stack — the half the catalogue above cannot show, and the
one where hand-written bricks double an extension the stack already offers. The stack runs
PostgreSQL 17.6: the hand-rolled `uuidv7()` is correct today and becomes dead weight the day
Supabase moves to 18, where it is native.

Installed:

- [ ] `pgcrypto` 1.3 — installed, called by nothing: `gen_random_uuid()` resolves to `pg_catalog` on
  PG 17, and `uuidv7()` is pure core SQL on purpose.
- [ ] `supabase_vault` 0.3.1 — installed, unused. Secrets live in the env file the process reads at
  boot, and no SQL needs one; Vault earns its place the day the database calls out itself — a
  `pg_net` webhook carrying a token.
- [ ] `uuid-ossp` 1.1 — installed, unused, and superseded: keys are `uuidv7()`, security tokens the
  core `gen_random_uuid()`.
- [ ] `pg_stat_statements` 1.11 — installed, unused. It sees what the hand-written SQL tally cannot —
  the heaviest statements across every session — and misses what the tally is for: which request
  ran them, the key `db.heavy_request` reports on.
  [sql_stats.py](apps/shared/persistence/sql_stats.py)

Available:

- [ ] `pg_net` 0.20.4 — available, not installed.
- [ ] `index_advisor` 0.2.0 + `hypopg` 1.4.1 — the cheapest win on the list: no coupling at all,
  installed for the length of a session, and it answers "DB indexes?" and the missing
  `issue_occurrences` index directly.
- [ ] `pg_partman` 5.3.1 — would replace `roll_log_partitions`, the hand-written SQL function that
  creates `log_lines`' daily partitions and applies retention. Rolling partitions is not a design
  choice, it is maintenance.
  [20260818000015_log_lines.sql:90](supabase/migrations/20260818000015_log_lines.sql#L90)
- [ ] `pgmq` 1.5.1 — Supabase's message queue: table, visibility timeout, archive. It keeps the
  outbox semantics, since `pgmq.send` is SQL and commits with the caller's session like today's
  insert. It covers the transport half of `apps/shared/queue.py`, not the rest: the acting user
  and its RLS session, attempts and parking, recurring singletons, and the reads behind the Tasks
  screen. The bet: less code, against a brick whose every line the README can no longer explain.
  [queue.py](apps/shared/queue.py)
- [ ] `pg_cron` 1.6.4 — would replace the wake-up of purges and rollups, today a re-enqueue in
  Python. It does not replace the queue, only the scheduling: still open whether splitting the
  recurring half in two is a simplification or one more seam. [queue.py:116](apps/shared/queue.py#L116)
- [ ] `vector` 0.8.2 — semantic search. To decide alongside Postgres FTS, which answers half of
  "search in pages" with no extension at all.
- [ ] `pg_jsonschema` 0.3.3 — would validate the JSONB columns in the database (fact payloads,
  occurrence context), where only Python constrains the shape today.
- [ ] `pg_graphql` 1.6.1 — a second generated face for the API. To weigh against the two-faces
  doctrine, which already makes every route readable as JSON.
- [ ] `postgres_fdw` 1.1 / `wrappers` 0.6.2 — read an external source as a Postgres table.
- [ ] `http` 1.6 — outbound calls from the database. Overlaps `pg_net`, the asynchronous one Supabase
  builds on.
- [ ] `pgsodium` 3.1.8 — per-column encryption at rest.
