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

Templates, tests, and BDD steps live with their context: `<context>/templates/`, `<context>/tests/` (incl. API + browser driver mixins), `<context>/tests/steps.py`. Shared layout sits in `app/shared/templates/`, Gherkin `.feature` files in `features/`, and shared E2E drivers in `tests/e2e/`. The `todo/`, `files/`, and `learning/` contexts are demos — each illustrates a pattern (`todo/` trivial CRUD, `files/` Supabase Storage + share tokens, `learning/` hexagonal architecture). Delete the ones you don't need when starting real work.

## Principles

**Context boundaries.** `domain/` never imports from `infra/`. Contexts never import each other — the only inter-app surface is `contract/` (owned public API). Cross-context orchestration lives at the composition root (`registration.py`, `seeding.py`), never in `shared/`.

**Cross-context communication.** `app/shared/` is ownerless infrastructure (clock, HTTP, DB sessions), not a coupling point. Two sanctioned forms: `contract/` for synchronous owned APIs, hooks for event-driven reactions where the emitter doesn't know its subscribers. Each context's FastAPI dependencies live in its own `contract/current.py` (`CurrentUser`/`RlsSession` in `auth/`, `CurrentOrg`/`CurrentMembership` in `organizations/`); `app/shared/` holds only ownerless infra, such as the BYPASSRLS `AdminSession`.

**HTTP layer.** `router.py` owns HTTP and nothing else — parsing, serialization, status codes. No business logic, no direct DB access. Each router serves both JSON and HTML/fragment via `wants_json(request)`.

**Data & persistence.** RLS is the single source of truth for isolation — row access is decided by policies in `supabase/migrations/`, never re-implemented in Python. Three session dependencies: `get_rls_session` (default), `get_user_session` (raw), `get_admin_session` (BYPASSRLS). supabase-py handles auth and storage only; business queries go through SQLAlchemy directly.

**Testing.** Tests are complete and sincere — no mocking the persistence layer, no bypassing HTTP, no shortcuts that hide real app state. E2E tests interact exclusively via HTTP endpoints or the browser UI. The same Gherkin scenarios run against both an API driver (fast) and a browser driver (Playwright).

Both drivers share a substrate in `tests/e2e/drivers/` (`ApiBase` / `BrowserBase`) that each context's feature mixins extend; the concrete driver just assembles those mixins. Every user gets an isolated session — its own httpx client, or its own browser context with a distinct cookie jar — so multi-user scenarios never bleed auth state. Isolation differs by driver: the API driver wraps each scenario in a rolled-back transaction; the browser driver runs an in-process Hypercorn server (so test and app share memory) and truncates app tables between scenarios.

**Time.** `clock.now()` is the single source of time. Never call `datetime.now()` directly.

**Audit events** are best-effort — fired as `BackgroundTasks`, loss on crash is acceptable. Never block a mutation to guarantee a write.

**Multi-tenancy.** Each account gets a personal org at sign-up; org-scoped data lives under `/{org_slug}/...`. Members read, owners write — gated by `CurrentOwnerMembership` for a clean `403`.

**Page composition.** The shell (`profile/contract/shell.py::shell_context`) is pulled in explicitly. No middleware injects data silently — full pages load the shell, HTMX fragments don't.

## Structure

Every bounded context follows the same layout — `domain/` (models, service), `infra/`
(router, repository), `templates/`, `tests/`, and an optional `contract/` (its public
inter-app surface). Three top-level modules form the composition root — the only place
allowed to know several contexts at once: `main.py`, `registration.py`, `seeding.py`:

```
labase.py/
├── app/
│   ├── main.py            # FastAPI app, router registration, 401 handler
│   ├── registration.py    # Composition root: sign-up saga (auth user + personal org)
│   ├── seeding.py         # Composition root: wires org.created subscribers
│   ├── shared/            # Cross-context infra: persistence (engines, rls), http
│   │                      #   (security, templates, limiter), observability, templates/
│   ├── auth/              # Authentication — get_current_user, get_rls_session, cookies
│   ├── organizations/     # Multi-tenant orgs, memberships, invitations
│   ├── profile/           # User profile + page shell (shell_context / page_context)
│   ├── files/             # Demo context — Supabase Storage + share tokens
│   ├── learning/          # Demo context — spaced repetition (HexArch example)
│   ├── console/           # SaaS admin console
│   ├── public/            # Public landing pages
│   ├── health/            # Liveness / readiness probes
│   └── todo/              # Demo context — trivial CRUD, full-pattern reference
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
make test-e2e     # pytest-bdd browser driver + Playwright E2E
make test-all     # test + test-e2e + coverage XML

make ci           # js-build + lint + typecheck + test + test-e2e + coverage XML
```
