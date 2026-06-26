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

Templates, tests, and BDD steps live with their context: `<context>/templates/`, `<context>/tests/e2e/` (incl. API + browser driver mixins), `<context>/tests/e2e/steps.py`. Shared layout sits in `apps/shared/templates/`, Gherkin `.feature` files in `features/`, and shared E2E drivers in `tests/e2e/drivers/`. The `todo/`, `files/`, and `learning/` contexts are demos — each illustrates a pattern (`todo/` trivial CRUD, `files/` Supabase Storage + share tokens, `learning/` hexagonal architecture). Delete the ones you don't need when starting real work.

> **Building a feature?** The `/feature` skill walks the BDD workflow phase by phase, each with a focused reference:
> [SKILL.md](.claude/skills/feature/SKILL.md) (overview) ·
> [scenarios](.claude/skills/feature/references/scenarios.md) (write the `.feature`) ·
> [impact](.claude/skills/feature/references/impact.md) (integration, surfaces, data) ·
> [design](.claude/skills/feature/references/design.md) (UI mockup) ·
> [build](.claude/skills/feature/references/build.md) (TDD + structure, events, observability, security, Tailwind, a11y).

### Integration & event bus

Each bounded context exposes a single `mount(app, host)` entry point in its `contract/integration.py`. The composition root (`apps/main.py`) calls them in dependency order — no context knows about another.

**`Host`** (`apps/shared/host.py`) carries two things:

- `events: EventBus` — type-keyed async pub/sub; handlers are registered by the Python type of the event, so there are no magic string names and no shared imports between contexts.
- `reserve(*slugs)` — claims URL path segments so no org handle can shadow them.

**`EventBus`** exposes two primitives:

| Method           | Semantic                                                        | On failure                                         | Used for                    |
| ---------------- | --------------------------------------------------------------- | -------------------------------------------------- | --------------------------- |
| `emit(event)`    | push / command — runs all handlers, returns their results       | propagates first exception (caller can compensate) | `UserCreated`, `OrgCreated` |
| `collect(query)` | pull / query — runs all handlers, aggregates successful returns | logs & skips the failing handler                   | `OverviewQuery` (dashboard) |

**Sign-up event chain:**

```
signup → emit(UserCreated)
  → organizations: creates personal org → emit(OrgCreated)
      → files:    seeds welcome.txt
      → learning: seeds Welcome deck
      → todo:     seeds 3 welcome todos
```

**Dashboard query:**

```
GET /{org}/ → collect(OverviewQuery)
  ← files, learning, todo each return an Overview (icon, title, counts, recent items)
     one context failing does not break the dashboard
```

## Principles

**Context boundaries.** `domain/` never imports from `infra/`. Contexts never import each other — the only inter-app surface is `contract/` (owned public API). Cross-context orchestration lives in application services inside the owning context (e.g. `auth/application.py`), never in `shared/`.

**Cross-context communication.** Two sanctioned forms: `contract/` for synchronous owned APIs (FastAPI dependencies, public types), and the `EventBus` for event-driven reactions where the emitter doesn't know its subscribers. Each context's FastAPI dependencies live in its own `contract/current.py` — `CurrentUser`, `OptionalCurrentUser`, `RlsSession` in `auth/`; `CurrentOrg`, `CurrentMembership`, `CurrentOwnerMembership` in `organizations/`. `apps/shared/` is ownerless infra (clock, HTTP, DB sessions) — not a coupling point; it holds only things no single context owns, such as the BYPASSRLS `AdminSession`.

**HTTP layer.** `router.py` owns HTTP and nothing else — parsing, serialization, status codes. No business logic, no direct DB access. Each router serves both JSON and HTML/fragment via `wants_json(request)`.

**Data & persistence.** RLS is the single source of truth for isolation — row access is decided by policies in `supabase/migrations/`, never re-implemented in Python. Three session dependencies: `get_rls_session` (default), `get_user_session` (raw), `get_admin_session` (BYPASSRLS). supabase-py handles auth and storage only; business queries go through SQLAlchemy directly.

**Testing.** Tests are complete and sincere — no mocking the persistence layer, no bypassing HTTP, no shortcuts that hide real app state. E2E tests interact exclusively via HTTP endpoints or the browser UI. The same Gherkin scenarios run against both an API driver (fast) and a browser driver (Playwright).

Both drivers share a substrate in `tests/e2e/drivers/` (`ApiBase` / `BrowserBase`) that each context's feature mixins extend; the concrete driver just assembles those mixins. Every user gets an isolated session — its own httpx client, or its own browser context with a distinct cookie jar — so multi-user scenarios never bleed auth state. Isolation differs by driver: the API driver wraps each scenario in a rolled-back transaction; the browser driver runs an in-process Hypercorn server (so test and app share memory) and truncates app tables between scenarios.

**Time.** `clock.now()` is the single source of time. Never call `datetime.now()` directly.

**Observability.** Structured logging via `structlog.get_logger("labase.<context>.<subject>")` — events are dotted `snake_case` with kwargs, never f-strings or `print`. The `RequestLogger` middleware binds a `request_id` (contextvars) so logs across a request correlate automatically.

**Audit events** are best-effort — fired as `BackgroundTasks`, loss on crash is acceptable. Never block a mutation to guarantee a write.

**Multi-tenancy.** Each account gets a personal org at sign-up; org-scoped data lives under `/{org_handle}/...`. Members read, owners write — gated by `CurrentOwnerMembership` for a clean `403`.

**Page composition.** The shell (`profile/contract/shell.py`) is pulled in explicitly via `page_context` (full pages) or `shell_context` (partial). No middleware injects data silently — full pages load the shell, HTMX fragments don't. Sidebar entries are registered in `mount()` via `host.register_nav(NavItem(...))`, or contributed dynamically per org through the `ShellOrgQuery` event.

**Toggleable apps.** A context declares its admin-tunable values with `declare_app_settings(...)` and can expose an on/off `feature_switch()`; when disabled, its `mount()` short-circuits but still answers `ConsoleOverviewQuery` so admins can re-enable it. The SaaS admin console (`settings/`) aggregates these server-wide stats (BYPASSRLS, across all orgs).

**Styling.** Tailwind with reusable component classes defined in `@layer components` in `static/css/input.css` (`btn-primary`, `input`, `card`, `list-panel`, `alert-*`, `page-title`…). Reuse them instead of re-spelling utility chains; markup follows semantic, accessible HTML (real landmarks, labelled controls, `aria-hidden` on decorative icons, visible focus rings).

## Structure

Every bounded context follows the same layout — `domain/` (models, service), `infra/`
(router, repository), `templates/`, `tests/`, and an optional `contract/` (its public
inter-app surface). One top-level module forms the composition root — the only place
allowed to know several contexts at once: `main.py`.

```
labase.py/
├── apps/
│   ├── main.py            # FastAPI app, router registration, 401 handler
│   ├── shared/            # Cross-context infra: EventBus (bus.py), Host (host.py),
│   │                      #   contract/integration.py (middleware/CORS/static),
│   │                      #   persistence, http, observability, templates/
│   ├── auth/              # Authentication — get_current_user, get_rls_session, cookies
│   ├── organizations/     # Multi-tenant orgs, memberships, invitations
│   ├── profile/           # User profile + page shell (shell_context / page_context)
│   ├── files/             # Demo context — Supabase Storage + share tokens
│   ├── learning/          # Demo context — spaced repetition (HexArch example)
│   ├── pages/             # Per-org Markdown pages with draft/members/public visibility + nav
│   ├── settings/          # App settings / SaaS admin console
│   ├── public/            # Public landing pages + public org pages (/{org_handle}/{slug})
│   ├── health/            # Liveness / readiness probes
│   └── todo/              # Demo context — trivial CRUD, the full-pattern reference:
│       ├── domain/        #   models.py (ORM + DTO); CRUD skips service.py
│       ├── infra/         #   router.py (HTML/JSON/HTMX), repository.py
│       ├── contract/      #   integration.py mount(): nav, settings, overview, seed
│       ├── templates/todo/#   list + _list_fragment (HTMX) + _overview (card)
│       └── tests/e2e/     #   steps.py, driver_mixin_{api,browser}.py
├── features/              # BDD Gherkin scenarios (plain text, no code)
├── tests/                 # pytest plugin entry (plugin.py) + config tests; e2e drivers in e2e/
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
- [Node.js](https://nodejs.org/) 24+ (Tailwind build)

### Steps

```bash
make install      # uv sync + pre-commit hooks + front-end assets (static/)
make db-start     # start local Supabase (first run pulls ~10 containers; applies migrations)
make env          # write .env from `supabase status -o env`
make dev          # Supabase + app via Docker Compose, hot-reload
```

App: http://localhost:8000 · Swagger: http://localhost:8000/docs

### Reference

**Local Supabase endpoints** (from `supabase status`):

| Interface           | URL                    | Purpose                                                     |
| ------------------- | ---------------------- | ----------------------------------------------------------- |
| **Supabase Studio** | http://localhost:54323 | Web UI: tables, Auth, Storage, SQL editor                   |
| **Supabase API**    | http://localhost:54321 | PostgREST, Auth API, Storage API                            |
| **Postgres direct** | localhost:54322        | psql or any SQL client (user: `postgres`, pass: `postgres`) |

**`.env` vs `.env.test`:**

| File        | Used by                                 | Hosts                        |
| ----------- | --------------------------------------- | ---------------------------- |
| `.env`      | `docker compose` (app container)        | `host.docker.internal:543xx` |
| `.env.test` | `make test` / `make test-e2e` (on host) | `localhost:543xx`            |

`make env` generates `.env` (mapping the Supabase CLI output to `SUPABASE_API_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `SUPABASE_DATABASE_USER_URL`, `SUPABASE_DATABASE_ADMIN_URL`, with the asyncpg driver and `host.docker.internal` host). `.env.test` is committed and uses `localhost`.

Notes:
- **Front-end assets** — `static/` is gitignored; re-run `make install` after adding a Tailwind class (unused ones are purged) or bumping a `package.json` dependency.
- **`COOKIES_SECURE=false`** is required over plain HTTP. Otherwise session cookies get the `Secure` flag and are dropped on non-HTTPS, returning 401 on every authenticated request.
- **Migrations** — `supabase start` and `make db-reset` apply `supabase/migrations/` locally. `make migrate` (`supabase db push`) is for a linked **remote** project.

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

make env          # Write .env from `supabase status -o env`
make install      # uv sync + pre-commit + .env + npm install + npm run build

make lint         # ruff check --fix
make format       # ruff format
make typecheck    # ty check
make quality      # lint + format + typecheck

make test         # pytest unit/integration (generates coverage)
make test-e2e     # pytest-bdd browser driver + Playwright E2E
make test-all     # test + test-e2e + coverage XML

make ci           # js-build + lint + format + typecheck + audit + test + test-e2e + coverage
```
