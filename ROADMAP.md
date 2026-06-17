## goals

### architecture gaps

- [x] `todo/` mutations (POST/PATCH/DELETE) don't return JSON — violates "Both JSON & HTML/fragment" principle
- [x] replace raw `datetime.now(UTC)` calls with `clock.now()` in `profile/infra/repository.py`, `files/infra/router.py`, `organizations/tests/test_invitations.py`
- [x] `auth/infra/router.py` imports `OrganizationRepository` from `organizations/infra/` directly — move org creation logic to `registration.py` (composition root)
- [ ] migrate context-owned dependencies from `shared/dependencies.py` into their respective `contract/` (e.g. `CurrentOrg` → `organizations/contract/`, `get_current_user` → `auth/contract/`)

### technical

- [ ] logs
- [ ] async task queue
- [ ] fulltext index
- [ ] cache
- [ ] messaging
- [ ] email
- [ ] prod deployment doc (secrets, env)

### functional

- [ ] public page
- [ ] user profile
- [ ] org dashboard
- [ ] admin console

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
