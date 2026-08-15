## à enquêter — audit code 2026-07 (candidats bugs/sécurité)

Trouvés par lecture du code. **Enquête bouclée 2026-07-21** : chaque candidat tracé bout-en-bout (code, rôles Postgres, migrations SQL, config). Verdict + sévérité en tête de ligne.


### confirmés mais by-design / latents (pas de fuite live)

- [ ] **[BY-DESIGN · 🟡 moyenne] Couper `two_factor_enabled` bypasse le TOTP des enrôlés.** Confirmé : `login` reçoit une session AAL1 complète, le challenge n'est déclenché que `if users_settings.two_factor_enabled` (setting **global** serveur), et GoTrue ne backstoppe pas l'usage général AAL1. **Mais volontaire** : kill-switch admin documenté (`two_factor.py:4-6`) pour authenticator perdu. Vrai défaut = granularité (global, tout-ou-rien, tout admin console peut le flip). Fix : reset per-user au lieu d'un toggle global. `apps/auth/infra/router.py:229-232`.
- [ ] **[LATENT · 🟡 moyenne] Redaction logs/business-events = match sur le *nom* du champ** (`token|password|secret` en substring). Prédicat confirmé, mais (a) `_loggable_payload` ne va **que** dans `business_events`, **pas les logs** ; (b) **aucun event ne porte** aujourd'hui `api_key`/`otp`/`reset_code` (secrets délibérément exclus des payloads). Fragile pour le futur contributeur, pas de fuite live. Fix : allowlist au lieu de denylist. `apps/shared/bus.py:29,38`.
- [ ] **[LATENT · 🟡 basse] Setting `"number"` mal typé silencieusement** — `_coerce` fait `int(raw)` et sur `ValueError` renvoie la *string* brute ; `"1.5"` relu comme `str`, floats non supportés. **Mais aucun setting déclaré n'utilise de défaut décimal** et le write path (`_normalise`) rejette les non-int → non atteignable aujourd'hui. `apps/shared/settings.py:117-125`.
- [ ] **[LATENT · 🟡 moyenne] Résolution templates = glob trié, pas de namespace par app** — mécanisme first-match-wins alphabétique confirmé, mais **aucune collision réelle** aujourd'hui (les apps se namespacent en sous-dossier). Latent : le jour où deux apps posent un `base.html`/`errors/404.html` racine. Fix : imposer la convention sous-dossier / namespacer le loader. `apps/shared/http/templates.py:20-22`.
- [ ] **[LATENT · 🟡 moyenne] Business-event fire-and-forget sans référence de task** — `asyncio.create_task(...)` résultat jeté, CPython peut GC la task en vol, rien ne draine au shutdown. Confirmé (les tasks sœurs `capture.py:104`/`firehose.py:213` gardent leur ref, seul le persister l'omet). Impact = trous sporadiques dans le trail (best-effort par doctrine, aucune mutation ne casse). Fix : set module-level + drain au shutdown. `apps/shared/observability/business_events.py:198`.
- [ ] **[PARTIEL · 🟡 basse-moyenne] Scope « une clé API = une org » = check Python, pas RLS** — la clé s'authentifie comme son créateur ; RLS seule verrait toutes ses orgs. Routes handle-scopées **protégées** par `_ensure_api_key_scope` dans `get_current_org` ; le bypass `{org_id}`+`require_owner` est **dormant** (non câblé). Fuite live réelle : `GET /organizations` énumère **toutes** les orgs du créateur, `POST /organizations` en crée. Fix : gate central des routes collection quand `api_key_org_id` est set. `apps/organizations/infra/context.py:62-69` + `router.py:157,198-207`.

## issues

- [x] id as uuid, not str or int
- [ ] aire passer le chemin clé d'API par les identifiants Storage de l'app, en gardant l'épinglage d'org comme source unique du chemin. Le précédent existe déjà dans la base : l'upload d'avatar utilise admin_storage() pour un utilisateur authentifié.
- [ ] _ENTITY_ROUTES in apps/organizations est un couplage
- [ ] jinja_globals should live in host ??
- [ ] 7 skipped
- [ ] réduire les "| None = None"
- [ ] moins de str, plus de types
- [ ] chasse aux N+1
- [ ] no more "audit event" > BusinessEvent, Issue or Log
- [ ] no more todo_completion_stats > real time count (to generalyze to all apps)
- [ ] split SQLAlchemy models in domain & Pydantic models in contract (all apps)
- [ ] _ACTIVITY_PAGE and any other constants should become settongs (all apps)
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
- [ ] `home.html` ignore `current_user` : un authentifié voit « Sign in » sur une instance sans org vedette
- [ ] AARRR metrics
- [ ] product tour
- [ ] awareness, @citation, notification

### technical

- [ ] squash migrations
- [ ] Role-Based Access Control
- [ ] dataclass or pydantic ?
- [ ] multi processes ?
- [ ] better styleguide inspired by my apps and daisyui templates
- [ ] event driven ?
- [ ] Command Query Responsibility Segregation ?
- [ ] SQLAlchemy exploiter plus à la JPA
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

### production readiness

Objectif 1 (contrats client) : passer de « ça tourne chez moi » à « livrable et exploitable ».
Déjà en place, à ne pas refaire : observabilité 4 couches, sondes `health/`, rate limiting
inter-instances (Postgres), RLS, en-têtes de sécurité (HSTS/CSP/X-Frame/nosniff dans
`apps/shared/http/security.py`), CSRF `Sec-Fetch-Site`, doc backups. Le trou n'est pas le
runtime, c'est le **chemin vers la prod et l'exploitation**.

#### P0 — bloquant pour un premier déploiement client

→ implémenté 2026-07-12, runbook complet dans [docs/production.md](docs/production.md).
Rebasé et vérifié 2026-08-15 : lint vert, `check_production` couvert par `apps/shared/tests/test_preflight.py`.

- [x] **`docker/docker-compose.prod.yml`** — compose de prod : `restart: unless-stopped`,
  `healthcheck` (python, pas curl — l'image slim n'a pas curl) sur `/health/ready`, limites
  CPU/mémoire, `stop_grace_period: 30s`.
- [x] **Terminaison TLS + reverse proxy** — `docker/Caddyfile` : Caddy devant, TLS auto
  Let's Encrypt (`DOMAIN`/`ACME_EMAIL` en env). HSTS déjà côté app → reste à soumettre au
  **preload** (opérationnel). (cf. Supabase « SSL enforcement » pour le lien app→DB.)
- [x] **`make preflight`** — gate `apps/shared/preflight.py` : refuse de booter en prod
  (`ENVIRONMENT`/`LABASE_ENV=production`) si `COOKIES_SECURE=false`, CORS `*`, DB en localhost,
  secret trop court ; warnings sinon. Enforce au boot **et** en CLI. (Durcissement CSP → P1,
  la CSP est une constante, pas un réglage.) = le `check --deploy` de cookiecutter.
- [x] **Pooling via Supavisor** — documenté dans docs/production.md (URLs via le pooler en mode
  transaction + sizing du pool asyncpg). Routage = config opérateur. (cf. « Supavisor » plus bas.)
- [x] **Flux de migration en prod** — cadré dans docs/production.md : forward-only, discipline
  expand→migrate→contract, `supabase db push` joué dans le pipeline, RLS dans la migration.
- [x] **Backup du Storage** — `scripts/backup_storage.py` + `make backup-storage` : miroir complet
  du bucket (récursif) sur disque. Reste à planifier (cron) + drill de restauration → P2.
- [x] **Arrêt gracieux** — `--graceful-timeout` (Hypercorn) dans `entrypoint.sh` + `stop_grace_period`
  compose ; le `TaskWorker` relâchait déjà ses locks proprement sur `stop()`.
- [x] **Doc secrets prod** — docs/production.md : injection via `env_file`/secret store, table des
  variables minimales (rappel : `.env` n'est **pas** commité, seul `.env.test` l'est).
- [ ] **Le seuil `len(SUPABASE_SECRET_KEY) < 40` du preflight est une heuristique** — il bloque
  le boot, sans échappatoire. Les `service_role` hérités sont des JWT très longs et passent ;
  le format `sb_secret_…` est bien plus court et sa longueur réelle n'est pas vérifiée. Un faux
  positif verrouille la prod dehors. Trancher : mesurer les deux formats et valider un préfixe
  plutôt qu'une longueur, ou rétrograder en warning. `apps/shared/preflight.py`.

#### P1 — juste après le premier deploy

- [ ] **CI/CD de déploiement** — pipeline gated sur `make ci`, build + push image taguée par
  **version** (`apps/issues` track déjà la régression par version — s'en servir), migration, rollback.
- [ ] **Alerting** (la télémétrie existe, pas la boucle) — sur régression d'issue, tâches *parkées*
  dans la file, seuils de charge (`/metrics` existe déjà), échecs readiness. Scrape Prometheus +
  dashboard Grafana.
- [ ] **Expédition des logs** — logs JSON structurés → agrégateur (Loki/CloudWatch/…).
  (cf. Supabase « Log Drains ».)
- [ ] **Scan d'image + secret-scan CI** — Trivy sur l'image ; talisman (déjà en pre-commit) promu
  en **gate CI** bloquant.
- [ ] **Durcir la CSP** — resserrer `script-src`/`connect-src` maintenant que le front est stable
  (HTMX, pas de JS externe).
- [ ] **Délivrabilité email** — un vrai provider derrière le `Mailer` port + SPF/DKIM/DMARC.
  (recoupe « email » ci-dessus.)
- [ ] **Monitoring d'uptime** — check synthétique externe sur `/health` readiness.

#### P2 — maturité d'exploitation

- [ ] **Drill de restauration automatisé** + cibles **RTO/RPO** écrites (le drill est documenté,
  pas testé en continu).
- [ ] **Runbooks** — deploy, incident, on-call ; doc SLO / error budget.
- [ ] **Timeouts explicites** sur tous les appels sortants (Supabase, SMTP) — la file a déjà le backoff.
- [ ] **Guide de scaling horizontal** — le `TaskWorker` est déjà multi-instances safe ; documenter
  le sizing pooler/workers + un load test au-delà du `perf-smoke`.

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
