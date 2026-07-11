## now — finir / fiabiliser (état des lieux 2026-07-11)

### auth — prouver que ça marche

- [x] OAuth round-trip untested end-to-end — settled by the documented manual smoke
      checklist (`docs/oauth.md`, "Manual verification, local stack"); callback
      branching now also covered by `apps/auth/tests/test_oauth_callback.py`
- [x] TOTP-after-OAuth branch (`apps/auth/infra/router.py:442`) has zero coverage
      → covered (session withheld until the code, cookies parked, opt-out paths)
- [ ] passkeys: the browser JS (`navigator.credentials`) is never executed by tests —
      Playwright virtual authenticator (CDP)
- [x] `/auth/confirm` error path redirects with `?info=registered`, key missing from
      `_INFO_MESSAGES` → blank banner — now `?info=confirm_failed` with a real message

### GUI — harmoniser

- [ ] land PR #4 — labase-light/labase-dark identity, shared type scale,
      hardcoded-color guardrail in `make lint`
- [ ] `page_header` macro + one content-width convention (~20 hand-rolled headers,
      3 idioms)
- [ ] `empty_state` macro (5 idioms today)
- [ ] shared `data_table` + `filter_bar` partials (logs/metrics/issues each invent
      their own)
- [ ] `input_field`: error + select variants (profile/settings fork the markup)
- [ ] one avatar-initials macro (3 spellings: base.html, profile.html, styleguide)

### dashboards — rendre vivants

- [ ] shared chart macro over the `charts.js` `data-chart-config` contract + a
      series-shaping helper (unlocks everything below)
- [ ] org dashboard: 14-day activity chart — `LogReader.activity(org_id=…)` already
      returns per-day/per-source counts
- [ ] profile: "Recent activity" timeline — `search_audit_logs(user_id=…)` already
      filters per user
- [ ] wire the `metric_card` stub ("No data yet") to the counts `overviews.json`
      already computes
- [ ] logs: replace the hand-rolled CSS activity bars with the ApexCharts stack
- [ ] issues: per-day occurrence sparkline on the detail page
- [ ] console: signups / orgs growth chart (`UserCreated`/`OrgCreated` or audit events)

### découplage — finaliser

- [ ] `host.register_app(manifest)`: collapse the ~15-step mount ceremony copy-pasted
      in todo/files/learning/pages/calendar (incl. the console-tile-before-enabled-gate
      ordering trap)
- [ ] declarative mount phases instead of the hand-ordered tuple in `apps/main.py`
- [ ] unify the four collect-slice queries (`OverviewQuery` / `ConsoleOverviewQuery` /
      `OrgSettingsSectionQuery` / `OrgNavQuery`)
- [x] one settings registry (`host.declarations` vs `settings._registry`) — the
      declaration now lives on the `AppSettings` handle only; `Host` indexes handles.
      Naming decision: "users"/"appearance" are deliberate admin-facing group names
      (renaming would migrate DB rows + URLs for no gain); documented on `Host` and
      in each declaring contract
- [x] import-linter: add the missing "logs internals are private" contract
- [x] one slug rule: drop calendar's (and pages') pointless `reserve`, move
      `register_open_list` onto `Host` — rule documented on `Host.reserve`

### vitrine

- [x] laudative Welcome page seeded public + in nav by `pages` on `OrgCreated` — set
      `public.featured_org_handle` to make it the site home


## goals

### technical

- [ ] awareness, @citation, notification
- [ ] export RGPD
- [ ] product tour
- [x] ApexCharts integration
- [ ] MCP server ?
- [ ] CLI
- [x] logs
- [x] ETag on public pages
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
- [ ] **i18n** — JHipster ships 45+ languages with a navbar switcher; all our UI
  strings are hardcoded English. Jinja2 route: Babel/gettext extraction, per-request
  locale (cookie or `Accept-Language`), catalogs per context. Expensive to retrofit
  later — decide early: if target products are French-speaking this is urgent,
  otherwise defer consciously.
  → decided 2026-07-05: **consciously deferred** — out of scope for now.
- [ ] **named permissions** — Lite's Jhiptser "Kipe" authorization module: permission model
  beyond binary roles. Our owner/member is binary; keep in mind for the first
  client contract needing custom roles.
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
  (2026-07-05: out of scope for now) https://github.com/t3dotgg/stripe-recommendations

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
