## à enquêter — audit code 2026-07 (candidats bugs/sécurité, non confirmés)

Trouvés par lecture du code, mécanisme vérifié mais impact réel à confirmer. 

- [ ] **Impersonation : le time-box de 3600 s sauté au refresh de token.** `get_current_user` rafraîchit le JWT expiré et ré-émet `access_token`/`refresh_token` avec le TTL de session normal (long), écrasant les cookies posés à `IMPERSONATION_MAX_SECONDS`. Le `IMPERSONATOR_COOKIE`, lui, n'est pas rafraîchi → à 3600 s la bannière + le stash meurent mais l'admin reste authentifié *en tant que* la cible. `apps/auth/infra/security.py:90` vs `apps/auth/infra/router.py:575-580`.
- [ ] **Couper `two_factor_enabled` bypasse le TOTP des utilisateurs déjà enrôlés.** `login` reçoit une session AAL1 complète de GoTrue ; le challenge n'est déclenché que `if users_settings.two_factor_enabled`. Setting serveur off → connexion mot-de-passe seul malgré un facteur vérifié. `apps/auth/infra/router.py:229-232`.
- [ ] **`RlsSession` anonyme = superuser, RLS entièrement bypassée (pas « voit rien », « voit tout »).** `get_rls_session` n'appelle `set_rls_context` que si `current_user is not None` ; sinon la connexion garde son rôle Postgres par défaut. À confirmer que le rôle prod de `SUPABASE_DATABASE_USER_URL` n'est pas superuser (en `.env.test` user == admin == `postgres`). Un read public monté sur `RlsSession` au lieu d'`AdminSession` = fuite cross-tenant. `apps/auth/infra/session.py:25-27` + `apps/shared/persistence/rls.py:32-38`.
- [ ] **`GET /{org}/pages/new/edit` mute** (crée un draft + `emit(PageCreated)`) → contourne le garde CSRF `Sec-Fetch-Site` (réservé aux mutations non-GET), prefetch/crawler/double-clic créent des brouillons orphelins. `apps/pages/infra/router.py:132-152`.
- [ ] **Rate limiter sans `X-Forwarded-For`** → derrière proxy/LB tout le monde collapse sur l'IP du proxy (limite globale) ; et **no-op silencieux** si le handler n'a pas de param `Request` ou `request.client is None`. Clé aussi = `func.__name__` → deux `create` de routers différents partagent un bucket. `apps/shared/http/limiter.py:85-89`.
- [ ] **Business-event fire-and-forget sans référence de task** — `asyncio.create_task(...)` résultat jeté ; CPython peut GC la task en vol sous charge, et rien ne la draine au shutdown. `apps/shared/observability/business_events.py:198`.
- [ ] **Redaction logs/business-events = match sur le *nom* du champ** (`token|password|secret` en substring). Un champ `api_key`/`otp`/`reset_code`/`session` passe en clair dans les logs ET dans `business_events`. Sûreté par discipline de nommage, pas par type. `apps/shared/bus.py:29,38`.
- [ ] **Invariant « dernier owner » Python-only** — `ensure_not_last_owner` (domain) seul garde-fou ; les policies RLS `self leave` / `owner delete` n'ont pas de condition last-owner → un chemin qui ne passe pas par le service peut orphaner l'org. `apps/organizations/domain/service.py:16-24`.
- [ ] **Dé-dup d'invitation case-sensitive côté Python, case-insensitive en SQL** — `Foo@x.com` et `foo@x.com` créent deux invitations, toutes deux acceptables par la même personne. `apps/organizations/infra/repository.py:158-168` vs migration `org_invitations.sql:66`.
- [ ] **CORS `*` + `allow_credentials=True`** par défaut — posture permissive out-of-the-box à revoir. `apps/shared/config.py:33` + `apps/shared/http/security.py:17-23`.
- [ ] **Scope « une clé API = une org » = check Python, pas RLS** — la clé s'authentifie comme son créateur ; RLS seule verrait toutes ses orgs. Toute route org-scopée qui ne passe pas par `get_current_org` + `OrgScopedRepository` laisse la clé atteindre les autres orgs du créateur. `apps/organizations/infra/context.py:62-69`.
- [ ] **Setting `"number"` mal typé silencieusement** — `_coerce` fait `int(raw)` et sur `ValueError` renvoie la *string* brute ; un défaut décimal (`"1.5"`) est relu comme `str`, l'erreur explose loin de la déclaration. Floats non supportés. `apps/shared/settings.py:117-125`.
- [ ] **Résolution templates = glob trié, pas de namespace par app** — deux apps avec un `_row.html` (ou `errors/404.html`) → l'app alphabétiquement première gagne, silencieusement. `apps/shared/http/templates.py:20-22`.

## issues

- [ ] /console/users bouton Accounts &  all organisations Users 13 users inerte
- [ ] /console/organizations should list organizations and give metrics
- [ ] audit des .goto() .fetch() code smells
- [ ] utiliser https://apexcharts.com/javascript-chart-demos/heatmap-charts/basic/
- [ ] https://apexcharts.com/javascript-chart-demos/sparklines/basic/

## goals

### features

- [x] console should list all business events from each app
- [x] profile & dashboard should display the recent business events
- [x] profile, dashboard & console should show a github like activity
- [ ] console should show a dedicated growth activity report
- [ ] AARRR metrics
- [ ] product tour
- [ ] awareness, @citation, notification

### technical

- [ ] dataclass or pydantic ?
- [ ] multi processes ?
- [ ] better styleguide inspired by my apps and daisyui templates
- [ ] event driven ? CQRS ?
- [ ] Command Query Responsibility Segregation ?
- [ ] DB index ?
- [ ] no audit() for error/exception, logger instead
- [ ] trop de fichiers racine
- [ ] export RGPD
- [ ] MCP server ?
- [ ] CLI
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
