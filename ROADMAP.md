## à enquêter — audit code 2026-07 (candidats bugs/sécurité)

Trouvés par lecture du code. **Enquête bouclée 2026-07-21** : chaque candidat tracé bout-en-bout (code, rôles Postgres, migrations SQL, config). Verdict + sévérité en tête de ligne.

### confirmés — à corriger

- [x] **[CORRIGÉ 2026-07-21 · était 🔴 haute] Impersonation : le time-box de 3600 s sauté au refresh de token.** Un cookie `impersonator_deadline` (deadline absolue) est posé à l'`impersonate` ; `get_current_user` cap le refresh sur le temps restant (`set_auth_cookies(max_age=…)`) et refuse (401) une fois la fenêtre écoulée → la session cible meurt avec la bannière. `apps/auth/infra/security.py` (`_impersonation_remaining`) + `cookies.py` + `router.py` + `contract/impersonation.py`. Tests : `test_refresh_while_impersonating_caps_cookie_to_window`, `test_refresh_after_impersonation_window_returns_401`.
- [x] **[CORRIGÉ 2026-07-21 · était 🔴 haute] CORS `*` + `allow_credentials=True`** par défaut. `cors_config` refuse désormais le combo : défaut fermé (`[]`), `*` = lecture publique sans credentials, credentials réservés à un allowlist explicite. `cors_origins` par défaut = `[]`. `apps/shared/http/security.py` + `apps/shared/config.py` + `.env.example`. Tests : `test_cors_closed_default_grants_nothing`, `test_cors_wildcard_drops_credentials`, `test_cors_explicit_allowlist_keeps_credentials`.
- [x] **[CORRIGÉ 2026-07-21 · était 🟠 haute, 3/3 sous-claims] Rate limiter sans `X-Forwarded-For`.** (a) Nouveau resolver partagé `client_ip` (`apps/shared/http/addressing.py`) honorant `X-Forwarded-For` quand `TRUST_FORWARDED_FOR` est activé (off par défaut, anti-spoof) — utilisé par le limiter et par `_client_ip` du router auth. (b) `request` manquant → `log.error` bruyant (fail-open par doctrine mais visible) ; `client_ip` None → `log.warning`. (c) Clé = `func.__module__ + func.__qualname__` → plus de collision entre `create` de routers différents. `apps/shared/http/limiter.py` + `addressing.py` + `config.py` + `.env.example`. Tests : `test_distinct_endpoints_do_not_share_a_bucket`, `test_missing_request_param_fails_open_but_logs_loudly`, `test_addressing.py`.
- [ ] **[CONFIRMÉ · 🟠 moyenne] `GET /{org}/pages/new/edit` mute** (crée un draft + `emit(PageCreated)`) → contourne le garde CSRF `Sec-Fetch-Site` (exempte GET par design). Membre authentifié requis, mais prefetch/crawler/link-preview/double-clic créent des brouillons orphelins qui s'accumulent (`page-2`, `page-3`…). Fix : POST pour la création, GET = rendu pur. `apps/pages/infra/router.py:132-152`.
- [ ] **[CONFIRMÉ · 🟠 moyenne — gap DB] Invariant « dernier owner » Python-only** — `ensure_not_last_owner` (domain) est le seul garde-fou et **toutes les routes in-app y passent** (leave/remove/update role). Mais **zéro garde DB** : les policies RLS `owner delete`/`self leave`/`owner update` n'ont pas de condition last-owner et `authenticated` a `DELETE`/`UPDATE` direct → un client PostgREST/supabase-js avec le JWT peut orphaner l'org. Fix : trigger `BEFORE DELETE/UPDATE` sur `memberships`. `apps/organizations/domain/service.py:16-24` + `migrations/…_organizations.sql:83-91`.
- [ ] **[CONFIRMÉ · 🟡 basse] Dé-dup d'invitation case-sensitive côté Python, case-insensitive à l'accept** — Python `email ==` (sensible), accept RPC `lower()`. `Foo@x.com` + `foo@x.com` créent deux invitations pending, toutes deux acceptables par la même personne (pas de crash, pas d'unique index — juste du clutter + cap gonflé). Fix : normaliser en lowercase à l'invite. `apps/organizations/infra/repository.py:158-168` + service `ensure_no_pending_invitation` vs `org_invitations.sql:66` (accept, pas contrainte table).

### confirmés mais by-design / latents (pas de fuite live)

- [ ] **[BY-DESIGN · 🟡 moyenne] Couper `two_factor_enabled` bypasse le TOTP des enrôlés.** Confirmé : `login` reçoit une session AAL1 complète, le challenge n'est déclenché que `if users_settings.two_factor_enabled` (setting **global** serveur), et GoTrue ne backstoppe pas l'usage général AAL1. **Mais volontaire** : kill-switch admin documenté (`two_factor.py:4-6`) pour authenticator perdu. Vrai défaut = granularité (global, tout-ou-rien, tout admin console peut le flip). Fix : reset per-user au lieu d'un toggle global. `apps/auth/infra/router.py:229-232`.
- [ ] **[LATENT · 🟡 moyenne] Redaction logs/business-events = match sur le *nom* du champ** (`token|password|secret` en substring). Prédicat confirmé, mais (a) `_loggable_payload` ne va **que** dans `business_events`, **pas les logs** ; (b) **aucun event ne porte** aujourd'hui `api_key`/`otp`/`reset_code` (secrets délibérément exclus des payloads). Fragile pour le futur contributeur, pas de fuite live. Fix : allowlist au lieu de denylist. `apps/shared/bus.py:29,38`.
- [ ] **[LATENT · 🟡 basse] Setting `"number"` mal typé silencieusement** — `_coerce` fait `int(raw)` et sur `ValueError` renvoie la *string* brute ; `"1.5"` relu comme `str`, floats non supportés. **Mais aucun setting déclaré n'utilise de défaut décimal** et le write path (`_normalise`) rejette les non-int → non atteignable aujourd'hui. `apps/shared/settings.py:117-125`.
- [ ] **[LATENT · 🟡 moyenne] Résolution templates = glob trié, pas de namespace par app** — mécanisme first-match-wins alphabétique confirmé, mais **aucune collision réelle** aujourd'hui (les apps se namespacent en sous-dossier). Latent : le jour où deux apps posent un `base.html`/`errors/404.html` racine. Fix : imposer la convention sous-dossier / namespacer le loader. `apps/shared/http/templates.py:20-22`.
- [ ] **[LATENT · 🟡 moyenne] Business-event fire-and-forget sans référence de task** — `asyncio.create_task(...)` résultat jeté, CPython peut GC la task en vol, rien ne draine au shutdown. Confirmé (les tasks sœurs `capture.py:104`/`firehose.py:213` gardent leur ref, seul le persister l'omet). Impact = trous sporadiques dans le trail (best-effort par doctrine, aucune mutation ne casse). Fix : set module-level + drain au shutdown. `apps/shared/observability/business_events.py:198`.
- [ ] **[PARTIEL · 🟡 basse-moyenne] Scope « une clé API = une org » = check Python, pas RLS** — la clé s'authentifie comme son créateur ; RLS seule verrait toutes ses orgs. Routes handle-scopées **protégées** par `_ensure_api_key_scope` dans `get_current_org` ; le bypass `{org_id}`+`require_owner` est **dormant** (non câblé). Fuite live réelle : `GET /organizations` énumère **toutes** les orgs du créateur, `POST /organizations` en crée. Fix : gate central des routes collection quand `api_key_org_id` est set. `apps/organizations/infra/context.py:62-69` + `router.py:157,198-207`.

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
