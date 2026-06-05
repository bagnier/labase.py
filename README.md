# labase.py

Python SaaS base, fully open-source, built on Supabase for the database, authentication, and file storage.

## Stack

| Layer                     | Choice                       | Reason                                                            |
| ------------------------- | ---------------------------- | ----------------------------------------------------------------- |
| **Web framework**         | FastAPI                      | Native async, Pydantic V2, auto-generated OpenAPI                 |
| **HTML rendering**        | Jinja2 + HTMX                | SSR without a JS build step, SPA-like dynamism via HTML fragments |
| **Styling**               | Tailwind CSS                 | CDN Play in dev, CLI in prod                                      |
| **ORM**                   | SQLModel (on SQLAlchemy 2.x) | Pydantic + SQLAlchemy models, async, Postgres-native              |
| **Auth + Storage**        | supabase-py                  | Official Supabase SDK, JWT stored in HTTPOnly cookie              |
| **Database**              | Supabase (Postgres)          | Hosted DB, RLS, triggers, Storage, Auth built-in                  |
| **Migrations**            | Supabase CLI (plain SQL)     | Versioned migrations, Studio integration, full control            |
| **ASGI server**           | Uvicorn                      | De facto standard for FastAPI                                     |
| **Dependency management** | uv                           | Ultra-fast, lockfile, built-in Python version management          |
| **Python**                | 3.14                         | Latest stable release                                             |

### Quality tools

| Tool                        | Purpose                                              |
| --------------------------- | ---------------------------------------------------- |
| **ruff**                    | Linting + formatting                                 |
| **ty**                      | Type checking (Astral, Rust)                         |
| **pytest + pytest-asyncio** | Unit and integration tests                           |
| **behave**                  | Functional BDD tests (Gherkin)                       |
| **pytest-cov**              | Code coverage (generates `coverage.xml` for VS Code) |

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
- Exception: `auth/infra/dependencies.py` (JWT guard) may be imported by other `infra/` routers

## Key design decisions

**Supabase as infrastructure layer** — supabase-py is limited to auth and storage. Business queries go through SQLAlchemy directly on Postgres, preserving flexibility (complex queries, transactions, pgvector…).

**SSR with HTMX instead of a separate SPA** — single repo, single deployment, no CORS, server-side auth. Well-suited for a SaaS whose UI is mostly CRUD.

**Plain SQL migrations** — Supabase CLI migrations stay readable and versioned in raw SQL. The initial migration creates the `profiles` table linked to `auth.users` with RLS and an auto-create trigger on sign-up.

**Functional BDD tests** — Gherkin scenarios (`features/`) drive the real HTTP API via `httpx.AsyncClient`. No network mocking: the app actually runs, validating routes, serialization, and HTTP responses end-to-end.

## Structure

```
labase.py/
├── app/
│   ├── main.py              # FastAPI app + lifespan, router registration
│   ├── shared/              # Cross-context infrastructure
│   │   ├── config.py        # Settings (pydantic-settings, .env)
│   │   ├── database.py      # SQLAlchemy async engine + session
│   │   └── supabase_client.py  # supabase-py clients (anon + admin)
│   ├── auth/                # Bounded context: authentication
│   │   ├── domain/
│   │   │   └── service.py   # login / logout / register logic
│   │   └── infra/
│   │       ├── router.py    # FastAPI endpoints + cookie handling
│   │       └── dependencies.py  # JWT guard (get_current_user)
│   ├── profile/             # Bounded context: user profile
│   │   ├── domain/
│   │   │   └── models.py    # SQLModel Profile entity
│   │   └── infra/
│   │       ├── repository.py  # Profile CRUD (SQLAlchemy)
│   │       └── router.py    # Dashboard + index redirect
│   └── templates/           # Jinja2 (base, auth, dashboard)
├── features/                # BDD Gherkin + behave steps
├── tests/                   # pytest fixtures
├── supabase/migrations/     # Versioned SQL (Supabase CLI)
├── Dockerfile               # Production image
├── Dockerfile.dev           # Dev image with hot-reload
├── docker-compose.yml       # App + local Supabase connection
└── Makefile                 # Common commands
```

## Local setup

### Prerequisites

- [uv](https://docs.astral.sh/uv/)
- [Docker](https://www.docker.com/)
- [Supabase CLI](https://supabase.com/docs/guides/cli)

### Install

```bash
# Clone and install dependencies
uv sync --all-groups

# Copy and fill in environment variables
cp .env.example .env
```

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
uv run uvicorn app.main:app --reload
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

make lint         # ruff check
make format       # ruff format
make typecheck    # ty check
make test         # pytest (generates coverage.xml)
make coverage     # pytest + open HTML coverage report in browser
make bdd          # behave (functional BDD tests)
```
