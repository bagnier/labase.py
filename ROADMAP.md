## issues

- [ ] better graphical language
- [x] réorganiser toute la console pour mettre les features en valeurs en les distingant des settings. issues, logs, metrics ne sont pas visibles
- [x] http://127.0.0.1:8000/az-az/learning/sessions cards should be displayed one by one
- [x] timezone in org, calendar accorded
- [x] apps/calendar should display multi-day events
- [x] apps/pages fulltext search
- [x] blue/black color of open links on http://127.0.0.1:8000/az-az/dashboard
- [x] org-settings divided into tabs : members, naming, api keys
- [x] org-settings save > confirm
- [x] org-settings save alignement
- [x] console setting for organizations to limit the number of invitation
- [x] profile divided into tabs : profile, organizations, email, authentication
- [x] console Per-organisation overrides, org finding uses current log  filter widgets
- [x] issues dont use the same graphic language that other
- [x] console load, where are the results ?
- [x] console load rename > metrics
- [x] organisations settings, limit the number of invitations
- [x] images for apps/pages
- [x] Per-organisation overrides not meaningful for featured_org_handle
- [x] http://127.0.0.1:8000/console/users "Accounts →" make it more visible
- [x] calendar new-event validation error re-renders the form as "Edit event" (title + breadcrumb) — `/{org}/calendar/new` — [preuve](reports/explore-2026-07-09/calendar-new-mislabel-edit.png)
- [x] console + metrics cards for API keys / Issues / Load show a blank icon (missing glyph) while other apps render one — [preuve](reports/explore-2026-07-09/v-console.png)
- [x] logs display, rework the GUI to match @features/unified-logs.mockup.html

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
