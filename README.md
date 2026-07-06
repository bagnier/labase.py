# labase.py

Python SaaS base, fully open-source, built on Supabase for the database, authentication,
and file storage — and a personal foundation for launching products fast.

## Objectives

This base exists for four reasons, in order:

1. **A personal SaaS boilerplate.** Clone it to turn a simple idea into a working app,
   prototype quickly, or answer a client contract with authentication, multi-tenancy,
   an admin console, and a full test harness already paid for. The demo apps are meant
   to be deleted when real work starts.

2. **Supabase as the platform, Postgres as everything.** Supabase provides the managed
   platform — database, auth, storage, migrations, and a growing feature catalog. On
   top of it, rather than bolting on Kafka, Elastic, Redis, or Mongo, the ambition is
   to rebuild those capabilities *on Postgres itself*: durable queues and streams,
   fulltext search, caching, document storage. The demo apps double as demonstrators
   of these bricks as they land. Plan and status: [ROADMAP.md](ROADMAP.md).

3. **Agent-driven development.** The base is optimized to be developed by AI agents
   under human direction. The skills in `.claude/skills/` are executable specs (the
   [`/feature`](.claude/skills/feature/SKILL.md) skill walks a full BDD workflow), the
   principles below are mechanically verifiable, and the dual-driver BDD suite is the
   verification substrate that makes agent-written features trustworthy. The ceremony
   you'll notice throughout is priced against that model: humans write scenarios and
   review diffs; agents write the plumbing; `make ci` arbitrates.

4. **Easy and confident new app creation.** The whole codebase should tend to ease the
   creation of any new app, CRUDished or HexArchished. Developers should be able to
   understand each line; conventions should be explicit, well named and documented.
   Integration with other apps should be intuitive and should not require modifying them.

## Principles

**Independent apps.** The base is a collection of self-contained apps (bounded
contexts): each owns its domain logic, routes, templates, tests and migrations, and can
be added, disabled, or deleted without touching the others. Boundaries are hard —
domain code never imports infrastructure; apps never import each other. The only
inter-app surfaces are each app's public contract and the event bus. These boundaries
are enforced by import-linter contracts (`[tool.importlinter]` in `pyproject.toml`),
checked by `make lint`.

**Every business endpoint has two faces.** The same handler serves the JSON API and the
HTML UI — a full page, or an HTMX fragment for in-page updates — through content
negotiation. One implementation buys a documented REST API *and* a server-rendered,
dynamic front end, with no separate frontend project and no JS build step.

**Integration is declarative.** An app states everything it contributes in a single
mount call: its routes, sidebar entry, dashboard card, admin-console stats, tunable
settings, on/off switch, and starter data for new organizations. Reactions to other
apps' flows travel through typed events — the emitter never knows its subscribers, and
deleting an app removes every trace of it.

**The admin console sees every app.** Each app reports server-wide stats to the SaaS
console, declares its admin-tunable settings there, and can be switched on or off at
runtime — a disabled app disappears everywhere but stays visible to admins for
re-enabling.

**The database enforces isolation.** Row-level security, versioned as plain SQL
migrations, is the single source of truth for who sees what. Python never re-implements
isolation for authenticated access (deviations are tracked in [ROADMAP.md](ROADMAP.md)).

**Observability is built in.** Structured, machine-readable logs correlated per
request; every domain event on the bus is logged; sensitive business actions are
audited to an append-only trail, browsable in the admin console. Auditing is
best-effort by doctrine — it never blocks a mutation.

**Tests are sincere.** The same plain-language scenarios run twice — over real HTTP and
through a real browser — against a real database. Nothing business-critical is mocked;
unit tests may stub external edges to reach error paths. For browser testing, goto() or
fetch() should be treated as possible code smells since we want to follow links and to
submit forms.

**Multi-tenancy by default.** Every account gets a personal organization at sign-up;
org data lives under `/{org_handle}/…`. Members read, owners write.

**First signed-up user is admin** and can then promote any other user as admin.

**One source of truth for the rest.** Time comes from a single clock; styling from one
component system (Tailwind + daisyUI); markup is semantic and accessible.

## The boilerplate

### Stack

| Layer                     | Choice                   | Reason                                                                    |
| ------------------------- | ------------------------ | ------------------------------------------------------------------------- |
| **Web framework**         | FastAPI                  | Native async, Pydantic V2, auto-generated OpenAPI                         |
| **HTML rendering**        | Jinja2 + HTMX            | SSR without a JS build step, SPA-like dynamism via HTML fragments         |
| **Styling**               | Tailwind CSS 4 + daisyUI | Component system without custom CSS; built via npm, served from `static/` |
| **ORM**                   | SQLAlchemy 2.x (async)   | Mapped ORM models for tables, Pydantic V2 for DTOs, Postgres-native       |
| **Auth + Storage**        | supabase-py              | Official Supabase SDK, JWT stored in HTTPOnly cookie                      |
| **Database**              | Supabase (Postgres)      | Hosted DB, RLS, triggers, Storage, Auth built-in                          |
| **Migrations**            | Supabase CLI (plain SQL) | Versioned migrations, Studio integration, full control                    |
| **ASGI server**           | Hypercorn                | ASGI server with HTTP/2 support                                           |
| **Dependency management** | uv                       | Ultra-fast, lockfile, built-in Python version management                  |
| **Python**                | 3.14                     | Latest stable release                                                     |

### Quality tools

| Tool                        | Purpose                                                                          |
| --------------------------- | -------------------------------------------------------------------------------- |
| **ruff**                    | Python linting + formatting                                                      |
| **Biome**                   | JS + CSS linting/formatting (`biome.json`, targets `static/js/` and `input.css`) |
| **djlint**                  | Jinja2 template linting (configured in `pyproject.toml`)                         |
| **ty**                      | Type checking (Astral, Rust)                                                     |
| **pre-commit**              | Git hooks — `ruff --fix`, `ruff format`, talisman on staged files                |
| **pytest + pytest-asyncio** | Unit and integration tests                                                       |
| **pytest-bdd + Playwright** | Functional BDD tests (Gherkin) — same scenarios run against API and real browser |
| **pytest-cov**              | Code coverage (generates `.cov/coverage.xml` for VS Code)                        |

### Architecture

Organized by **bounded context**, each split into `domain/` (business logic,
framework-free) and `infra/` (router, repository, framework I/O):

```
HTTP request → infra/router.py → domain/service.py → infra/repository.py → DB / external service
```

Routers own HTTP and nothing else — parsing, serialization, status codes; no business
logic, no direct DB access. Every business route answers three audiences from one
handler: **JSON** (`wants_json`), **HTMX fragment** (partial templates named `_*.html`),
or **full page** — the shared helpers in `apps/shared/http/` absorb the branching.

Templates, tests, and BDD steps live with their context: `<context>/templates/`,
`<context>/tests/e2e/` (incl. API + browser driver mixins), `<context>/tests/e2e/steps.py`.
Shared layout sits in `apps/shared/templates/`, Gherkin `.feature` files in `features/`,
and shared E2E drivers in `tests/e2e/drivers/`.

### Integration — between apps, and with the admin console

Each bounded context exposes a single `mount(host)` entry point in its
`contract/integration.py` — the FastAPI app is carried by `host.app`. The composition
root (`apps/main.py`) calls them in dependency order; no context knows about another.
At mount time, an app declares **every surface it contributes**:

| Surface           | Declared via                    | Shows up as                                                                                                     |
| ----------------- | ------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Routes            | `host.app.include_router(...)`  | its pages and JSON API                                                                                          |
| Sidebar           | `host.register_nav(...)`        | a global nav entry (per-org entries answer the `OrgNavQuery` event)                                             |
| Org dashboard     | handling `OverviewQuery`        | a card with counts and recent items on `/{org}/`                                                                |
| **Admin console** | handling `ConsoleOverviewQuery` | server-wide stats in the SaaS console (across all orgs)                                                         |
| **Settings**      | `declare_app_settings(...)`     | admin-tunable values, live-reloaded on `SettingsChanged`                                                        |
| Feature switch    | a declared on/off setting       | the app can be disabled at runtime; its `mount()` short-circuits but the console still lists it for re-enabling |
| Seeding           | handling `OrgCreated`           | starter data for every new organization                                                                         |
| URL safety        | `host.reserve(...)`             | its path segments can't be shadowed by an org handle                                                            |

Because every surface is registered rather than hardcoded, **deleting an app removes its
nav entry, dashboard card, console stat and seeds automatically** — this is what makes
the demo apps disposable.

**`EventBus`** (on `host.events`) exposes two primitives — handlers are keyed by the
Python type of the event, so there are no magic strings and no shared imports:

|                | `emit(event)`                                             | `collect(query)`                                                |
| -------------- | --------------------------------------------------------- | --------------------------------------------------------------- |
| **Semantic**   | push / command — runs all handlers, returns their results | pull / query — runs all handlers, aggregates successful returns |
| **On failure** | propagates first exception (caller can compensate)        | logs & skips the failing handler                                |
| **Used for**   | `UserCreated`, `OrgCreated`, `SettingsChanged`            | `OverviewQuery`, `ConsoleOverviewQuery`, `OrgNavQuery`          |

**Sign-up event chain:**

```
signup → emit(UserCreated)
  → organizations: creates personal org → emit(OrgCreated)
      → files:    seeds welcome.txt
      → learning: seeds Welcome deck
      → todo:     seeds 3 welcome todos
      → calendar: seeds a welcome event
```

**Dashboard query:**

```
GET /{org}/ → collect(OverviewQuery)
  ← files, learning, todo, calendar, pages each return an Overview (icon, title, counts, recent items)
     one context failing does not break the dashboard
```

### Observability

Three layers, all wired by default:

- **Structured logs** — `structlog.get_logger("labase.<context>.<subject>")`; events
  are dotted `snake_case` with kwargs, never f-strings or `print`. JSON output in
  production, pretty console in dev.
- **Request correlation** — the `RequestLogger` middleware binds a `request_id`
  (contextvars), so every log line of a request correlates automatically. Every domain
  event emitted through the bus is logged too (with sensitive fields redacted).
- **Audit trail** — sensitive business actions go through `record_audit_event`: logged
  immediately, then persisted to the append-only `audit_logs` table as a background
  task. The admin console ships an **audit viewer** with cursor pagination. Auditing is
  best-effort by doctrine: a lost audit write never blocks or fails a mutation.

### Conventions

**Auth & sessions.** Each context's FastAPI dependencies live in its own
`contract/current.py` — `CurrentUser` / `OptionalCurrentUser` (auth), `CurrentOrg`,
`CurrentMembership`, `CurrentOwnerMembership` (organizations, clean `403` for
non-owners). Three DB session dependencies: `RlsSession` (default — RLS enforced),
`get_user_session` (raw), `AdminSession` (BYPASSRLS — reserved for event handlers,
console queries, and anonymous public surfaces such as share-token downloads, where no
JWT exists and checks are explicit).

**Content negotiation.** `wants_json(request)` / `wants_full_page(request)` and the
`render_list(...)` helper in `apps/shared/http/` centralize the JSON / fragment / page
branching. Fragments are standalone valid markup (they're swapped into the live DOM).

**Page composition.** A full page's context is assembled from *slices*, each owned by
the app that knows it. Apps register a provider at mount time with declared, prefixed
keys (collisions rejected at startup); the ownerless collector in `apps/shared/page.py`
merges them — called explicitly, never injected silently.

**Time.** `clock.now()` is the single source of time. Never call `datetime.now()`.

**Styling.** daisyUI 5 is the component system (`btn`, `card`, `input`, `alert`,
`badge`, `stat`, `menu`…). Project-specific component classes live in
`@layer components` in `static/css/input.css` (`list-panel`, `md-body`). Reuse
components instead of re-spelling utility chains; keep one-off layout inline. Icons are
Phosphor. Markup uses real landmarks, labelled controls, `aria-hidden` on decorative
icons, visible focus rings.

**Testing.** Both E2E drivers share a substrate in `tests/e2e/drivers/` that each
context's feature mixins extend. Every actor in a scenario gets an isolated session —
its own httpx client, or its own browser context with a distinct cookie jar — so
multi-user scenarios never bleed auth state. The API driver wraps each scenario in a
rolled-back transaction; the browser driver runs an in-process Hypercorn server and
truncates app tables between scenarios. The browser driver navigates like a human:
entry point, then links and forms — no deep URLs.

### Structure

Every bounded context follows the same layout — `domain/` (models, service), `infra/`
(router, repository), `templates/`, `tests/`, and an optional `contract/` (its public
inter-app surface). One top-level module forms the composition root — the only place
allowed to know several contexts at once: `main.py`.

```
labase.py/
├── apps/
│   ├── main.py            # FastAPI app, mounts every context in dependency order
│   ├── shared/            # Cross-context infra: EventBus (bus.py), Host (host.py),
│   │                      #   contract/integration.py (middleware/CORS/static),
│   │                      #   persistence, http, observability, templates/
│   ├── auth/              # Authentication — current user, RLS sessions, cookies
│   ├── api_keys/          # Per-org machine credentials for the JSON API (Bearer)
│   ├── organizations/     # Multi-tenant orgs, memberships, invitations
│   ├── profile/           # User profile
│   ├── pages/             # Per-org Markdown pages with draft/members/public visibility + nav
│   ├── settings/          # App settings / SaaS admin console (stats, settings, audit viewer)
│   ├── public/            # Public landing pages + public org pages (/{org_handle}/{slug})
│   ├── health/            # Liveness / readiness probes
│   ├── todo/              # Demo — trivial CRUD, the full-pattern reference (see below)
│   ├── files/             # Demo — Supabase Storage + share tokens
│   ├── learning/          # Demo — spaced repetition, the most domain-heavy example
│   └── calendar/          # Demo — org calendar (month grid, agenda)
├── features/              # BDD Gherkin scenarios (plain text, no code)
├── tests/                 # pytest plugin entry (plugin.py) + config tests; e2e drivers in e2e/
├── static/                # Compiled CSS, HTMX, fonts (gitignored)
├── supabase/migrations/   # Versioned SQL (Supabase CLI)
├── client/                # Generated Python API client (labase-client, see below)
├── docs/                  # Generated schema documentation (one .md per table)
├── docker/                # Dockerfile(s), docker-compose.yml, entrypoint.sh
├── package.json           # Tailwind + daisyUI build, Biome
└── Makefile               # Common commands
```

### The generated API client — `client/`

Because every business endpoint also speaks JSON, the OpenAPI schema is a full
description of the app — `make client-gen` regenerates a typed Python client
from it (`openapi-python-client`, package `labase-client`). It is generated
code: never edit it, re-run `make client-gen` after changing routes or DTOs.

Today it has one consumer: the Locust perf smokes (`perf/`, `make perf-smoke`)
drive the API through it, which keeps the client honest — a route or DTO drift
breaks the smoke run. It is also the natural starting point for any external
Python integration against a product built on this base.

### Backups

Postgres is backed up by the platform; Storage bytes are not in any SQL dump.
What is covered by what, PITR, and the restore drill: [docs/backups.md](docs/backups.md).

### Local setup

Prerequisites: [uv](https://docs.astral.sh/uv/), [Docker](https://www.docker.com/),
[Supabase CLI](https://supabase.com/docs/guides/cli), [Node.js](https://nodejs.org/) 24+.

```bash
make install
make dev
```

App: http://localhost:8000 · Swagger: http://localhost:8000/docs

**Local Supabase endpoints** (from `supabase status`):

| Interface           | URL                    | Purpose                                                     |
| ------------------- | ---------------------- | ----------------------------------------------------------- |
| **Supabase Studio** | http://localhost:54323 | Web UI: tables, Auth, Storage, SQL editor                   |
| **Supabase API**    | http://localhost:54321 | PostgREST, Auth API, Storage API                            |
| **Postgres direct** | localhost:54322        | psql or any SQL client (user: `postgres`, pass: `postgres`) |
| **Mail catcher**    | http://localhost:54324 | Inbucket/Mailpit — captures all auth emails locally         |

**`.env` vs `.env.test`:**

| File        | Used by                                 | Hosts                        |
| ----------- | --------------------------------------- | ---------------------------- |
| `.env`      | `docker compose` (app container)        | `host.docker.internal:543xx` |
| `.env.test` | `make test` / `make test-e2e` (on host) | `localhost:543xx`            |

`make env` generates `.env` (mapping the Supabase CLI output to `SUPABASE_API_URL`,
`SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `SUPABASE_DATABASE_USER_URL`,
`SUPABASE_DATABASE_ADMIN_URL`, with the asyncpg driver and `host.docker.internal` host).
`.env.test` is committed and uses `localhost`.

Notes:
- **Front-end assets** — `static/` is gitignored; re-run `make install` after adding a
  Tailwind class (unused ones are purged) or bumping a `package.json` dependency.
- **`COOKIES_SECURE=false`** is required over plain HTTP. Otherwise session cookies get
  the `Secure` flag and are dropped on non-HTTPS, returning 401 on every authenticated
  request.
- **Migrations** — `supabase start` and `make db-reset` apply `supabase/migrations/`
  locally. `make migrate` (`supabase db push`) is for a linked **remote** project.

### Parallel work: isolated worktrees

To develop several features in parallel without their data colliding — and so `make ci`
never wipes your `make dev` data — each git worktree gets its **own** Postgres schema,
Storage bucket and app port, all on the **single** shared local Supabase stack (no second
`supabase start`). This is also what makes parallel agent-driven development safe.

```bash
make worktree NAME=calendar     # creates worktrees/calendar
cd worktrees/calendar && make dev   # → its own port (e.g. http://localhost:8019)
make worktree-rm NAME=calendar  # removes worktree + schema + bucket
```

Per worktree `<name>`:

| Resource  | Dev (`make dev`)    | Test (`make ci`)        |
| --------- | ------------------- | ----------------------- |
| DB schema | `wt_<name>`         | `wt_<name>_test`        |
| Bucket    | `org-files-<name>`  | `org-files-<name>-test` |
| App port  | derived from name   | in-process              |
| Dev user  | `<name>@labase.dev` | —                       |

The schema is a structural clone of `public` (`scripts/provision_schema.py` — a `pg_dump`
of `public`, rewritten to the target schema, plus the Storage bucket/policies and a
per-schema signup trigger). **Auth (GoTrue / `auth.users`) is shared**: isolation there is
logical — the dev user is namespaced by email, and `make ci` only purges its own
test-email domains. A `node_modules` symlink and `uv sync` mean a worktree needs no full
reinstall. The same mechanism makes the main repo's own tests run in a real `test` schema
(`make provision-test`, run automatically by `make test`), so they no longer touch
`public` / your `make dev` data.

### Commands

```bash
make dev          # Start Supabase + Docker Compose in dev mode (hot-reload)
make up           # Docker Compose in background
make down         # Stop containers
make logs         # App logs

make db-start     # Start local Supabase
make db-stop      # Stop local Supabase
make db-reset     # Wipe and reset local DB
make migrate      # Apply migrations (supabase db push)

make env          # Write .env from `supabase status -o env`
make upgrade-base # Product clones: merge the latest base (see docs/upgrade-base.md)
make worktree NAME=x     # New git worktree with its own schema/bucket/port
make worktree-rm NAME=x  # Remove it (worktree + schema + bucket)

make install      # Supabase + uv sync + pre-commit + npm install + .env + npm run build

make lint         # ruff + import-linter + ty + biome + djlint + pip-audit, read-only
make fix          # ruff --fix + format + import-linter + ty + biome + djlint --reformat
make doctor       # local stack reachability AND latency (catches a wedged Docker proxy)

make test         # pytest unit/integration (generates coverage)
make test-e2e     # pytest-bdd browser driver + Playwright E2E
make perf-smoke   # Locust smoke over the generated API client (blocking thresholds)

make finalize     # js-build + fix + test (run before committing)
make ci           # js-build + lint + test + test-e2e + perf-smoke + coverage, all steps run even if one fails
```

## Demo apps — and how to build your own

Four contexts are demos. Each illustrates one pattern of the base; all are meant to be
**deleted when real work starts** — and because every surface (nav, dashboard card,
console stat, seeds) is event-registered, removing an app leaves no trace.

| Demo        | Illustrates                                                                                                                            |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `todo/`     | trivial CRUD wired to every surface — nav, dashboard overview, console overview, settings, feature switch, seeding, both test drivers. |
| `files/`    | Supabase Storage: uploads, org-scoped buckets, immutable share tokens for anonymous download.                                          |
| `learning/` | The most domain-heavy example: spaced repetition with pure domain functions in `domain/service.py`.                                    |
| `calendar/` | A richer org-scoped app: month grid, agenda view, datetime handling.                                                                   |

### Building a feature

The [`/feature`](.claude/skills/feature/SKILL.md) skill drives the whole workflow in
four validated phases, each with a focused reference: Scenarios, Impact, Design, Build
