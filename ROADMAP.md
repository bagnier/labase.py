## cadre général

- une base pour toute application pro / Saas
- fondée sur Supabase
- en Python moderne


## buts

### technique

- [x] uv
- [x] python 3.14
- [x] fastAPI
- [x] pytest
- [x] séparation en apps
- [x] BDD dual driver, Json & Web
- [x] SSR HTMX
- [x] migrations database
- [ ] collaboration par hooks entre les apps
- [x] CORS
- [x] headers de sécurité (HSTS, CSP)
- [x] healthcheck (liveness / readiness)
- [x] rate-limiting
- [x] logging
- [x] observabilité
- [x] TLS and HTTP/2
- [x] OWASP Dependency Check
- [ ] transactions
- [x] upgrade
- [ ] file de tâches asynchrones
- [ ] index fulltext
- [ ] cache
- [ ] messaging
- [ ] email
- [ ] doc déploiement prod (secrets, env)
- [ ] GitHub Actions
- [ ] refactor / simplify migration

### fonctionnel

- [x] authentification
- [x] création de compte
- [x] creation d'organisation
- [x] partage de l'ownership d'organisation
- [x] ajout et revocation de membres
- [x] invitations par token (accept flow)
- [x] todo list comme exemple CRUD
- [x] gestion de fichiers (bucket + share tokens)
- [ ] flashcards comme exemple HexArch
- [ ] dashboard user (contexte testé mais router non câblé dans main.py)
- [ ] admin dashboard


### défauts à corriger

#### 1. Correction / sécurité (prioritaire)

- [x] Client supabase-py singleton avec état de session partagé — supabase.py met en cache un seul Client pour tout le process. Or sign_in_with_password y stocke la session : sous trafic concurrent, le client retient la session du dernier connecté, et logout() (service.py:33-38) fait sign_out() sur cet état partagé — au mieux un no-op, au pire la révocation du token d'un autre utilisateur. En plus, ces appels sont synchrones et bloquent l'event loop dans des handlers async (y compris le refresh dans security.py:38-48). Fix : client async stateless (ou par appel), sans rien changer fonctionnellement.

- [x] Inscription non atomique + violation de votre propre règle de couplage — router.py:100-121 : register() crée le user Supabase puis l'org via une session admin ; si la création d'org échoue, user orphelin. Et auth importe OrganizationRepository, ce que le README interdit. Vous avez déjà le pattern qui résout les deux : le trigger Postgres qui auto-crée profiles. Le même trigger peut créer org + membership — moins de code Python, atomicité gratuite, et un premier pas concret vers l'item « collaboration par hooks » de la roadmap.

- [x] Le domain d'organizations dépend de l'infra et de FastAPI — service.py importe infra/repository et lève des HTTPException, en contradiction directe avec les deux règles affichées du README. Pour une base censée montrer le pattern, c'est le mauvais exemple à copier. (Accepter un protocole et lever des exceptions domaine suffit.)

- [x] Un seul flag debug pilote trois comportements de sécurité — cookies sans Secure (cookies.py), rate-limiting désactivé (limiter.py), niveau de log. Quelqu'un qui active DEBUG=true en prod pour diagnostiquer perd silencieusement le rate-limiting et les cookies sécurisés.

- [x] /health/ready renvoie str(e) (router.py:21) — fuite de détails internes (DSN, host) sur un endpoint non authentifié.

#### 2. Réduction du boilerplate (le cœur de votre objectif)

- [ ] Alias Annotated pour les dépendances — chaque endpoint répète 4 paramètres Depends(...) (~30 endpoints). Des alias partagés (CurrentUser, RlsSession, CurrentOrg, AdminSession) dans shared/ suppriment 3-4 lignes par endpoint, idiome FastAPI standard.

- [ ] Négociation de contenu dupliquée 3 fois — _wants_json / _is_htmx / _html_template / _template_ctx + le re-render de liste sont copiés à l'identique dans todo/router.py, files/router.py et partiellement invitations. Un seul helper render_list(request, template, items, schema) dans shared/http réduit chaque endpoint à sa logique métier.

- [ ] Les checks d'autorisation copiés-collés — le bloc « get_membership → 404 → role != owner → 403 » apparaît 6 fois dans organizations/router.py. Une dépendance require_owner (sur le modèle de get_current_membership) les remplace toutes.

- [ ] commit() dans chaque méthode de repository — c'est ce qui rend l'item « transactions » de la roadmap impossible aujourd'hui : on ne peut pas composer deux opérations atomiquement. Déplacer le commit à la frontière de requête (dans get_user_session/get_rls_session) supprime une ligne par méthode de repo et donne les transactions gratuitement — votre harness de test (SAVEPOINT sur connexion partagée) le supporte déjà tel quel.

- [ ] Registre de templates manuel — templates.py liste chaque dossier ; un glob sur app/*/templates supprime cette étape d'enregistrement pour chaque nouveau contexte.

#### 4. Architecture, mineur
- [ ] /dashboard et / vivent dans le contexte profile (router.py:21-37) alors qu'un contexte dashboard existe avec ses tests mais sans router — la roadmap le note déjà ; c'est un déménagement, pas du code neuf.

- [ ] get_current_org consomme une session admin (BYPASSRLS) à chaque requête (context.py) — soit une 2ᵉ connexion DB par requête pour un simple check d'accès, résolvable via la session RLS (les policies memberships permettent de voir ses propres memberships).

- [ ] Détection d'erreur par matching de string — invitation_router.py:142 teste "invitation not found" in str(exc) : fragile, un SQLSTATE custom (RAISE ... USING ERRCODE) est aussi simple et stable.



### intégration possibles à Supabase

- [ ] AI Integrations - Enhance applications with OpenAI and Hugging Face integrations.
- [ ] Auth Hooks - Customize authentication flows with serverless functions.
- [ ] Authorization via Row Level Security - Control the data each user can access with Postgres Policies.
- [ ] Auto-generated GraphQL API via pg_graphql - Fast GraphQL APIs using our custom Postgres GraphQL extension.
- [ ] Auto-generated REST API via PostgREST - RESTful APIs auto-generated from your database.
- [ ] Automatic Embeddings - Automated embedding generation using triggers and queues.
- [ ] CLI - Use our CLI to develop your project locally and deploy.
- [ ] Captcha protection - Add Captcha to your sign-in, sign-up, and password reset forms.
- [ ] Client Library - Python - Integrate Supabase easily into your Python applications.
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
- [ ] Email login - Build email logins for your application or website.
- [ ] File storage - Supabase Storage makes it simple to store and serve files.
- [ ] Foreign Data Wrappers - Query external data sources as Postgres tables.
- [ ] Foreign Key Selector - Easily manage foreign key relationships between tables.
- [ ] Image transformations - Optimize and resize images on-the-fly directly from your Supabase storage buckets.
- [ ] JWT Signing Keys - Asymmetric key management for enhanced JWT security.
- [ ] Log Drains - Export logs to Datadog, Grafana, Sentry, S3, and more — now available on Pro.
- [ ] Logs & Analytics - Gain insights into your application’s performance and usage.
- [ ] Multi-Factor Authentication (MFA) - Add an extra layer of security to your application with MFA.
- [ ] Network restrictions - Restrict IP ranges that can connect to your database.
- [ ] OAuth2.1 Server - Turn your project into an OAuth 2.1 identity provider.
- [ ] Passwordless login via Magic Links - Build passwordless logins via magic links for your application or website.
- [ ] Persistent Storage - Mount S3 buckets for 97% faster Edge Function cold starts.
- [ ] Phone logins - Provide phone logins using a third-party SMS provider.
- [ ] Policy Templates - Quickly implement common security policies.
- [ ] Postgres Extensions - Enhance your database with popular Postgres extensions.
- [ ] Postgres Roles - Managing access to your Postgres database and configuring permissions.
- [ ] Postgres database - Every project is a full Postgres database.
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
