# labase.py

Python SaaS base, fully open-source, built on Supabase for the database, authentication, and file storage.

## Stack

| Layer                     | Choice                       | Reason                                                            |
| ------------------------- | ---------------------------- | ----------------------------------------------------------------- |
| **Web framework**         | FastAPI                      | Native async, Pydantic V2, auto-generated OpenAPI                 |
| **HTML rendering**        | Jinja2 + HTMX                | SSR without a JS build step, SPA-like dynamism via HTML fragments |
| **Styling**               | Tailwind CSS                 | Built via npm CLI (`make install`), served from `static/`         |
| **ORM**                   | SQLAlchemy 2.x (async)       | Mapped ORM models for tables, Pydantic V2 for DTOs, Postgres-native |
| **Auth + Storage**        | supabase-py                  | Official Supabase SDK, JWT stored in HTTPOnly cookie              |
| **Database**              | Supabase (Postgres)          | Hosted DB, RLS, triggers, Storage, Auth built-in                  |
| **Migrations**            | Supabase CLI (plain SQL)     | Versioned migrations, Studio integration, full control            |
| **ASGI server**           | Uvicorn                      | De facto standard for FastAPI                                     |
| **Dependency management** | uv                           | Ultra-fast, lockfile, built-in Python version management          |
| **Python**                | 3.14                         | Latest stable release                                             |

### Quality tools

| Tool                        | Purpose                                                                          |
| --------------------------- | -------------------------------------------------------------------------------- |
| **ruff**                    | Linting + formatting                                                             |
| **pre-commit**              | Git hooks — runs `ruff format` on staged files before each commit                |
| **ty**                      | Type checking (Astral, Rust)                                                     |
| **pytest + pytest-asyncio** | Unit and integration tests                                                       |
| **pytest-bdd + Playwright** | Functional BDD tests (Gherkin) — same scenarios run against API and real browser |
| **pytest-cov**              | Code coverage (generates `.cov/coverage.xml` for VS Code)                        |

## Architecture

The project is organized by **bounded context**, each split into `domain/` and `infra/` layers.

```
HTTP request
  → infra/router.py       (FastAPI endpoint)
  → domain/service.py     (business logic, no framework dependencies)
  → infra/repository.py   (SQLAlchemy, Supabase SDK)
  → DB / external service
```

**Coupling rules:**
- `domain/` never imports from `infra/`
- Contexts don't import each other directly — shared infrastructure goes through `app/shared/`
- Exception: `auth/infra/security.py` (`get_current_user`) and `auth/infra/session.py` (`get_rls_session`) are the shared JWT guard / RLS-session dependencies, imported by other `infra/` routers

**Templates are colocated** — each context owns its Jinja2 templates under `<context>/templates/`. Shared layout lives in `app/shared/templates/`.

**Tests are colocated** — each context owns its unit/integration tests under `<context>/tests/` and its browser E2E tests under `<context>/e2e/`. Gherkin `.feature` files live in `features/` at the root; the corresponding pytest-bdd step implementations are in `<context>/tests/steps.py`.

## Demo context: `todo/`

The `todo` bounded context is an intentional example. It demonstrates the full pattern — model, repository, router, Jinja2 templates, BDD steps, E2E tests — on a trivial domain. When starting a new SaaS, delete it and use it as a reference for your first real context.

## Key design decisions

**Real RLS security model (hybrid)** — two Postgres connection pools: a *user pool* (`DATABASE_URL`, role `authenticated`, RLS enforced) and a *service pool* (`DATABASE_URL_SERVICE`, role `postgres`, BYPASSRLS for migrations and admin jobs). Every authenticated HTTP request calls `bind_rls(session, user_id)` which issues `SET role authenticated` and injects the user's JWT claims via `set_config('request.jwt.claims', ...)`, enabling Postgres `auth.uid()` in all policies. The service connection is only used for registration (org creation) and org-resolution infrastructure — never for user data queries.

**Supabase as infrastructure layer** — supabase-py is limited to auth and storage. Business queries go through SQLAlchemy directly on Postgres, preserving flexibility (complex queries, transactions, pgvector…).

**SSR with HTMX instead of a separate SPA** — single repo, single deployment, no CORS, server-side auth. Well-suited for a SaaS whose UI is mostly CRUD.

**Plain SQL migrations** — Supabase CLI migrations stay readable and versioned in raw SQL. The initial migration creates the `profiles` table linked to `auth.users` with RLS and an auto-create trigger on sign-up.

**Dual-driver BDD tests** — Gherkin scenarios (`features/`) are written in functional business language and run against two drivers: an API driver (`httpx.AsyncClient`, fast, no browser) and a browser driver (Playwright Chromium). The same scenarios exercise both the HTTP layer and the real UI without duplicating test logic.

**Front-end assets via npm** — `npm run build` does three things: copies `htmx.min.js` from `node_modules`, copies Inter font woff2 files into `static/fonts/`, and compiles `static/input.css` → `static/tailwind.css` via the Tailwind CLI. All output lands in `static/` and is committed. Re-run `make install` after any template change that adds new Tailwind classes. No CDN in production.

## Structure

```
labase.py/
├── app/
│   ├── main.py              # FastAPI app, router registration, 401 handler
│   ├── shared/              # Cross-context infrastructure
│   │   ├── config.py        # Settings (pydantic-settings, .env)
│   │   ├── database.py      # Async engines (user + service) + sessions
│   │   ├── base.py          # SQLAlchemy DeclarativeBase
│   │   ├── rls.py           # bind_rls / reset_rls (injects JWT claims)
│   │   ├── supabase_client.py  # supabase-py clients (anon + admin)
│   │   ├── templates.py     # Jinja2 environment
│   │   ├── clock.py         # now() — patched via module ref in tests
│   │   ├── utils.py         # Shared helpers
│   │   └── templates/       # base.html, macros, shared layouts
│   ├── auth/                # Bounded context: authentication
│   │   ├── domain/service.py
│   │   ├── infra/router.py
│   │   ├── infra/security.py      # get_current_user (JWT decode)
│   │   ├── infra/session.py       # get_rls_session (JWT guard + RLS claims)
│   │   ├── infra/cookies.py       # set/clear auth cookies
│   │   ├── templates/       # login.html, register.html
│   │   ├── tests/           # Unit + BDD steps + API driver
│   │   └── e2e/             # Playwright browser tests
│   ├── organizations/       # Bounded context: multi-tenant orgs + memberships + invitations
│   │   ├── domain/models.py
│   │   ├── infra/repository.py
│   │   ├── infra/router.py          # JSON API
│   │   ├── infra/html_router.py     # org settings + members (HTMX)
│   │   ├── infra/invitation_router.py  # token-based accept flow
│   │   ├── infra/context.py         # get_current_org / get_current_membership
│   │   ├── templates/
│   │   └── tests/
│   ├── profile/             # Bounded context: user profile
│   │   ├── domain/models.py
│   │   ├── infra/repository.py
│   │   ├── infra/router.py
│   │   ├── templates/
│   │   ├── tests/
│   │   └── e2e/
│   ├── dashboard/           # View context (no domain layer)
│   │   ├── tests/
│   │   └── e2e/
│   ├── files/               # Bounded context: org files (Supabase Storage + share tokens)
│   │   ├── domain/models.py
│   │   ├── infra/repository.py
│   │   ├── infra/storage.py
│   │   ├── infra/router.py
│   │   ├── templates/
│   │   ├── tests/
│   │   └── e2e/
│   └── todo/                # Demo context — full pattern example
│       ├── domain/models.py
│       ├── infra/repository.py
│       ├── infra/router.py
│       ├── templates/
│       ├── tests/
│       └── e2e/
├── features/                # BDD Gherkin scenarios (plain text, no code)
├── tests/                   # Top-level conftest + config tests
├── static/                  # Compiled CSS, HTMX, fonts
├── supabase/migrations/     # Versioned SQL (Supabase CLI)
├── docker/                  # Docker assets
│   ├── Dockerfile           # Production image
│   ├── Dockerfile.dev       # Dev image with hot-reload
│   ├── docker-compose.yml   # App + local Supabase connection
│   └── entrypoint.sh
├── package.json             # Tailwind CLI
└── Makefile                 # Common commands
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

`static/` is committed and served directly by Uvicorn. `make install` copies HTMX and Inter fonts from `node_modules` and compiles `static/input.css` → `static/tailwind.css` via Tailwind CLI.

Re-run `make install` whenever you add a new Tailwind class (unused classes are purged) or upgrade a `package.json` dependency.

### `.env` vs `.env.test`

| File        | Used by                                  | Hosts                        |
| ----------- | ---------------------------------------- | ---------------------------- |
| `.env`      | `docker compose` (app container)         | `host.docker.internal:543xx` |
| `.env.test` | `make test` / `make test-e2e` (on host)  | `localhost:543xx`            |

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
# or without Docker:
make serve        # uvicorn on port 8002 with .env.test
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
make serve        # uvicorn on port 8002 (test env, no Docker)

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
