# labase.py

Python SaaS base, fully open-source, built on Supabase for the database, authentication, and file storage.

## Stack

| Layer                     | Choice                   | Reason                                                              |
| ------------------------- | ------------------------ | ------------------------------------------------------------------- |
| **Web framework**         | FastAPI                  | Native async, Pydantic V2, auto-generated OpenAPI                   |
| **HTML rendering**        | Jinja2 + HTMX            | SSR without a JS build step, SPA-like dynamism via HTML fragments   |
| **Styling**               | Tailwind CSS             | Built via npm CLI (`make install`), served from `static/`           |
| **ORM**                   | SQLAlchemy 2.x (async)   | Mapped ORM models for tables, Pydantic V2 for DTOs, Postgres-native |
| **Auth + Storage**        | supabase-py              | Official Supabase SDK, JWT stored in HTTPOnly cookie                |
| **Database**              | Supabase (Postgres)      | Hosted DB, RLS, triggers, Storage, Auth built-in                    |
| **Migrations**            | Supabase CLI (plain SQL) | Versioned migrations, Studio integration, full control              |
| **ASGI server**           | Hypercorn                | ASGI server with HTTP/2 support                                     |
| **Dependency management** | uv                       | Ultra-fast, lockfile, built-in Python version management            |
| **Python**                | 3.14                     | Latest stable release                                               |

### Quality tools

| Tool                        | Purpose                                                                                   |
| --------------------------- | ----------------------------------------------------------------------------------------- |
| **ruff**                    | Linting + formatting                                                                      |
| **pre-commit**              | Git hooks — runs `ruff --fix` (lint) and `ruff format` on staged files before each commit |
| **ty**                      | Type checking (Astral, Rust)                                                              |
| **pytest + pytest-asyncio** | Unit and integration tests                                                                |
| **pytest-bdd + Playwright** | Functional BDD tests (Gherkin) — same scenarios run against API and real browser          |
| **pytest-cov**              | Code coverage (generates `.cov/coverage.xml` for VS Code)                                 |

## Architecture

Organized by **bounded context**, each split into `domain/` (business logic, framework-free) and `infra/` (router, repository, framework I/O):

```
HTTP request → infra/router.py → domain/service.py → infra/repository.py → DB / external service
```

### Coupling rules

- `domain/` never imports from `infra/`.
- Contexts never import each other directly — cross-cutting code lives in `app/shared/`.
- The only shared dependencies that cross context boundaries are the two auth ones: `get_current_user` (`auth/infra/security.py`) and `get_rls_session` (`auth/infra/session.py`).
- Org-scoped contexts (`todo`, `files`, `learning`) touch `organizations` only for org resolution (`CurrentOrg`, `CurrentMembership`, `Organization`) — never its logic.

### Core principles

1. **Explicit page composition.** A page is fragments, each owned by a context. The cross-cutting shell (sidebar nav + display name) is a provider — `profile/infra/shell.py::shell_context` — pulled in explicitly via `page_context(...)`. No middleware or Jinja context processor injects data silently; full pages load the shell, HTMX fragments don't.
2. **Multi-org users.** Each account gets a personal org at sign-up and can join others; the sidebar lists all of them (`nav_orgs`) and org-scoped data lives under `/{org_slug}/...`.
3. **Membership reads, ownership writes.** A member sees all of an org's data; owner-only actions are gated by a *single* app check (`CurrentOwnerMembership` / `OwnerMembership`) that exists only to return a clean `403`. Isolation is RLS's job, never re-implemented in Python.
4. **One query per context, per page.** The shell resolves display name + orgs in one query; org-scoped repositories are already org-filtered. Providers compose without N+1.

### Colocation

Templates, tests, and BDD steps live with their context: `<context>/templates/`, `<context>/tests/` (incl. API + browser driver mixins), `<context>/tests/steps.py`. Shared layout sits in `app/shared/templates/`, Gherkin `.feature` files in `features/`, and shared E2E drivers in `tests/e2e/`. The `todo/` context is a deliberately trivial, full-pattern reference — delete it when starting real work.

## Key design decisions

- **RLS is the single source of truth for isolation.** Two pools: *user* (`DATABASE_URL`, role `authenticated`, RLS enforced) and *service* (`DATABASE_URL_SERVICE`, role `postgres`, BYPASSRLS — migrations/admin/registration only). `get_rls_session` sets the RLS context (`SET role authenticated` + JWT claims) **once** per request; FastAPI's dependency cache means the shell, route, and sub-dependencies share that one session. Row access is decided only by policies in `supabase/migrations/`; the app's only authorization is the owner gate (for a friendly `403`).
  - Three session dependencies — pick deliberately: `get_rls_session` (**default** for authenticated routes — wraps the user session and sets the RLS context), `get_user_session` (user pool but raw — you must call `set_rls_context` yourself), `get_admin_session` (BYPASSRLS — admin jobs and registration only, never user data).
- **Supabase as infrastructure only.** supabase-py handles auth and storage; business queries go through SQLAlchemy on Postgres directly (complex queries, transactions, pgvector…).
- **SSR + HTMX, no SPA.** Single repo, single deployment, no CORS, server-side auth — suited to a mostly-CRUD UI.
- **Plain SQL migrations.** Supabase CLI migrations stay readable and versioned; the first creates `profiles` linked to `auth.users` with RLS and an auto-create trigger on sign-up.
- **Dual-driver BDD.** The same Gherkin scenarios run against an API driver (`httpx.AsyncClient`, fast) and a browser driver (Playwright), exercising both the HTTP layer and the real UI without duplicate test logic. Tests share one BYPASSRLS connection, so the `get_rls_session` override sets JWT claims *without* `SET role authenticated` — issuing it would drop BYPASSRLS and break unrelated queries on the shared connection.
- **npm-built assets, no remote dependencies at runtime.** All JS libraries and fonts are installed via `npm` and copied to `static/js/` at build time (`npm run build`). No CDN URLs in templates — add a library with `npm install`, copy it in `package.json`'s `build:js` step, and reference it as `/static/js/<file>`. Output lands in the gitignored `static/js/`; run `make install` to (re)generate.

## Structure

Every bounded context follows the same layout — `domain/` (models, service), `infra/`
(router, repository), `templates/`, and `tests/`:

```
labase.py/
├── app/
│   ├── main.py            # FastAPI app, router registration, 401 handler
│   ├── shared/            # Cross-context infra: persistence (engines, rls), http
│   │                      #   (security, templates, limiter), observability, templates/
│   ├── auth/              # Authentication — get_current_user, get_rls_session, cookies
│   ├── organizations/     # Multi-tenant orgs, memberships, invitations
│   ├── profile/           # User profile + page shell (shell_context / page_context)
│   ├── files/             # Org files (Supabase Storage + share tokens)
│   ├── learning/          # Spaced-repetition learning
│   ├── console/           # SaaS admin console
│   ├── public/            # Public landing pages
│   ├── health/            # Liveness / readiness probes
│   └── todo/              # Demo context — full pattern example
├── features/              # BDD Gherkin scenarios (plain text, no code)
├── tests/                 # Top-level conftest + config tests
├── static/                # Compiled CSS, HTMX, fonts (gitignored)
├── supabase/migrations/   # Versioned SQL (Supabase CLI)
├── docker/                # Dockerfile(s), docker-compose.yml, entrypoint.sh
├── package.json           # Tailwind CLI
└── Makefile               # Common commands
```

## Local setup

### Prerequisites

- [uv](https://docs.astral.sh/uv/)
- [Docker](https://www.docker.com/)
- [Supabase CLI](https://supabase.com/docs/guides/cli)
- [Node.js](https://nodejs.org/) (Tailwind build)
- [pre-commit](https://pre-commit.com/) (`uv tool install pre-commit`)

### Install

```bash
make install
```

This runs `uv sync`, installs pre-commit hooks, copies `.env.example → .env` (if not present), and builds front-end assets.

### Front-end assets

`static/` is gitignored and must be built before running the app. `make install` copies HTMX and Inter fonts from `node_modules` and compiles `static/input.css` → `static/tailwind.css` via Tailwind CLI.

Re-run `make install` whenever you add a new Tailwind class (unused classes are purged) or upgrade a `package.json` dependency.

### `.env` vs `.env.test`

| File        | Used by                                 | Hosts                        |
| ----------- | --------------------------------------- | ---------------------------- |
| `.env`      | `docker compose` (app container)        | `host.docker.internal:543xx` |
| `.env.test` | `make test` / `make test-e2e` (on host) | `localhost:543xx`            |

The app container reaches Supabase via `host.docker.internal` (mapped by `extra_hosts` in `docker/docker-compose.yml`). Tests run directly on the host, so they use `localhost`.

**`DEBUG=true`** must be set in both files while running over plain HTTP. Without it, session cookies are set with the `Secure` flag and the browser (or httpx) silently drops them on non-HTTPS connections, causing every authenticated request to return 401.

### Start Supabase locally

```bash
make db-start
```

`supabase start` downloads and starts about ten Docker containers (Postgres, Auth, Storage, Studio…). The first run takes a few minutes.

Once started, `supabase status` prints the URLs and keys to copy into `.env`:

```
API URL:          http://localhost:54321
DB URL:           postgresql://postgres:postgres@localhost:54322/postgres
Studio URL:       http://localhost:54323
anon key:         eyJ...
service_role key: eyJ...
```

| Interface           | URL                    | Purpose                                                     |
| ------------------- | ---------------------- | ----------------------------------------------------------- |
| **Supabase Studio** | http://localhost:54323 | Web UI: tables, Auth, Storage, SQL editor                   |
| **Supabase API**    | http://localhost:54321 | PostgREST, Auth API, Storage API                            |
| **Postgres direct** | localhost:54322        | psql or any SQL client (user: `postgres`, pass: `postgres`) |

### Apply migrations

```bash
make migrate      # supabase db push — applies supabase/migrations/
make db-reset     # wipe and replay all migrations from scratch
```

### Start the application

```bash
make dev          # Supabase (host) + app via Docker Compose with hot-reload
```

| Interface             | URL                        |
| --------------------- | -------------------------- |
| **App**               | http://localhost:8000      |
| **OpenAPI / Swagger** | http://localhost:8000/docs |

## Commands

```bash
make dev          # Docker Compose in dev mode (hot-reload)
make up           # Docker Compose in background
make down         # Stop containers
make logs         # App logs

make db-start     # Start local Supabase
make db-stop      # Stop local Supabase
make db-reset     # Wipe and reset local DB
make migrate      # Apply migrations (supabase db push)

make install      # uv sync + pre-commit + .env + npm install + npm run build

make lint         # ruff check --fix
make format       # ruff format
make typecheck    # ty check
make quality      # lint + format + typecheck

make test         # pytest unit/integration (generates coverage)
make test-e2e     # pytest-bdd browser driver + Playwright E2E (requires running app)
make test-all     # test + test-e2e + coverage XML

make ci           # js-build + lint + typecheck + test + test-e2e + coverage XML
```
