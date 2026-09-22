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
   to rebuild those capabilities _on Postgres itself_. The first bricks have landed:
   a durable task queue, error tracking, log storage, load metrics, rate limiting and
   fulltext search over pages — plain Postgres, no new infrastructure. Caching and
   document storage are next.

3. **Agent-driven development.** The base is optimized to be developed by AI agents
   under human direction. The agent works from written procedures versioned with the 
   code, the principles below are mechanically verifiable, and the dual-driver BDD 
   suite is the verification substrate that makes agent-written features trustworthy. 
   The ceremony you'll notice throughout is priced against that model: humans decide 
   the scenarios and review the diffs; agents draft them and write the plumbing;
   `make finalize` arbitrates.

4. **Easy and confident new app creation.** The whole codebase should tend to ease the
   creation of any new app, CRUDished or HexArchished. Developers should be able to
   understand each line; conventions should be explicit, well named and documented.
   Integration with other apps should be intuitive and should not require modifying them.
   The [`/feature`](.claude/skills/feature/SKILL.md) skill is the walkthrough: from
   scenarios to code in four validated phases, for a feature or a whole new app.

## Principles

Each principle is written out in [AGENTS.md](AGENTS.md), the text the agents building this base work from.

- [Demo apps are disposable, the others loosely coupled](AGENTS.md#demo-apps-are-disposable-the-others-loosely-coupled)
- [Every business endpoint has two faces](AGENTS.md#every-business-endpoint-has-two-faces)
- [Integration is declarative](AGENTS.md#integration-is-declarative)
- [Business events are facts, not sagas](AGENTS.md#business-events-are-facts-not-sagas)
- [The admin console sees every app](AGENTS.md#the-admin-console-sees-every-app)
- [The database enforces isolation and authorization](AGENTS.md#the-database-enforces-isolation-and-authorization)
- [Facts, traces, bugs: three records](AGENTS.md#facts-traces-bugs-three-records)
- [Tests are sincere](AGENTS.md#tests-are-sincere)
- [Multi-tenancy by default](AGENTS.md#multi-tenancy-by-default)
- [The first to sign up is admin](AGENTS.md#the-first-to-sign-up-is-admin)
- [One clock, one key, one style](AGENTS.md#one-clock-one-key-one-style)
- [Invariants are types, not checks](AGENTS.md#invariants-are-types-not-checks)
- [No magic number](AGENTS.md#no-magic-number)
- [`| None` means optional](AGENTS.md#-none-means-optional)

## The boilerplate

How the base applies them, convention by convention, also written out in [AGENTS.md](AGENTS.md):

- [Architecture](AGENTS.md#architecture)
- [Integration — between apps, and with the admin console](AGENTS.md#integration--between-apps-and-with-the-admin-console)
  - [A contract never exports a settings handle](AGENTS.md#a-contract-never-exports-a-settings-handle)
  - [Two collaboration objects, two shapes](AGENTS.md#two-collaboration-objects-two-shapes)
  - [`host.events` — push](AGENTS.md#hostevents--push)
  - [An app may subscribe to its own business event](AGENTS.md#an-app-may-subscribe-to-its-own-business-event)
  - [Signing in is one fact](AGENTS.md#signing-in-is-one-fact)
  - [`host.contribs` — pull](AGENTS.md#hostcontribs--pull)
  - [Sign-up event chain](AGENTS.md#sign-up-event-chain)
  - [Dashboard query](AGENTS.md#dashboard-query)
  - [Import downward, event upward](AGENTS.md#import-downward-event-upward)
- [Observability](AGENTS.md#observability)
  - [The journal — what changed the domain](AGENTS.md#the-journal--what-changed-the-domain)
  - [The log sink — a trace of the machinery](AGENTS.md#the-log-sink--a-trace-of-the-machinery)
  - [What earns a line](AGENTS.md#what-earns-a-line)
  - [Nothing escapes it](AGENTS.md#nothing-escapes-it)
  - [Issues — a bug, with a lifecycle](AGENTS.md#issues--a-bug-with-a-lifecycle)
  - [What counts as a bug](AGENTS.md#what-counts-as-a-bug)
  - [A failure that repeats is one bug](AGENTS.md#a-failure-that-repeats-is-one-bug)
  - [The Timeline reads all three](AGENTS.md#the-timeline-reads-all-three)
  - [Load metrics](AGENTS.md#load-metrics)
- [Conventions](AGENTS.md#conventions)
  - [Auth & sessions](AGENTS.md#auth--sessions)
  - [Sign-in surface](AGENTS.md#sign-in-surface)
  - [Background work](AGENTS.md#background-work)
  - [HTTP security](AGENTS.md#http-security)
  - [Content negotiation](AGENTS.md#content-negotiation)
  - [A form is JSON at the door](AGENTS.md#a-form-is-json-at-the-door)
  - [Page composition](AGENTS.md#page-composition)
  - [Time](AGENTS.md#time)
  - [Identity](AGENTS.md#identity)
  - [Styling](AGENTS.md#styling)
  - [Testing](AGENTS.md#testing)
  - [Anti-flake e2e](AGENTS.md#anti-flake-e2e)

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
| **Biome**                   | JS + CSS + JSON linting/formatting (`biome.json`)                                |
| **djlint**                  | Jinja2 template linting (configured in `pyproject.toml`)                         |
| **sqlfluff**                | SQL migration linting — lint-light, no reformat (`scripts/.sqlfluff`, Postgres)  |
| **gplint**                  | BDD `.feature` structure linting (`scripts/.gplintrc`)                           |
| **yamllint**                | YAML linting (`scripts/.yamllint`)                                               |
| **validate-pyproject**      | `pyproject.toml` schema validation                                               |
| **zizmor**                  | GitHub Actions security linting (`.github/zizmor.yml`)                           |
| **droast**                  | Dockerfile linting — self-contained GitHub Action in CI (`.github/workflows/`)   |
| **ty**                      | Type checking (Astral, Rust)                                                     |
| **pyright**                 | Type checking, and the language server the editors and the agent run             |
| **import-linter**           | Architecture boundaries between apps (contracts in `pyproject.toml`)             |
| **pip-audit**               | Dependency vulnerability audit                                                   |
| **pre-commit**              | Git hooks — `ruff --fix`, `ruff format`, talisman on staged files                |
| **pytest + pytest-asyncio** | Unit and integration tests                                                       |
| **pytest-bdd + Playwright** | Functional BDD tests (Gherkin) — same scenarios run against API and real browser |
| **coverage**                | Code coverage — both lanes, combined (`.cache/cov/coverage.xml` for VS Code)     |

### Structure

Every bounded context follows the same layout — `domain/` (models, service), `infra/`
(router, repository), `templates/`, `tests/`, and an optional `contract/` (its public
inter-app surface). One top-level module forms the composition root — the only place
allowed to know several contexts at once: `main.py`.

```
labase.py/
├── apps/
│   ├── main.py            # FastAPI app, mounts every context in phase order (catch-alls last)
│   ├── shared/            # Cross-context infra — one package per subsystem, one module per brick:
│   │   ├── events/        #   business facts: the journal, its catalog, the bus and the listener
│   │   ├── logs/          #   technical traces: the chain, the sink, the capture seam, the verdicts
│   │   ├── settings/      #   every value the code reads, by lifetime — env (boot) vs live (console)
│   │   ├── persistence/   #   engines, sessions, RLS context, ORM mixins, SQL instrumentation
│   │   ├── http/          #   the request/response edge: negotiation, security, rate limiting
│   │   ├── integration/   #   the mount surface: Host, contribs registry, fullpage slices, slugs
│   │   ├── contract/      #   integration.py — the foundation's own mount: middleware, CORS, static
│   │   ├── templates/     #   the shared layout and macros every app's templates extend
│   │   └── *.py           #   single-module bricks: queue, email, clock, charts, overview…
│   ├── auth/              # Authentication — current user, RLS sessions, cookies
│   ├── api_keys/          # Per-org machine credentials for the JSON API (Bearer)
│   ├── organizations/     # Multi-tenant orgs, memberships, invitations
│   ├── profile/           # User profile
│   ├── pages/             # Per-org Markdown pages with draft/members/public visibility + nav
│   ├── console/           # SaaS admin console — server-wide stats, settings, admins, appearance
│   ├── timeline/          # The unified read view: log sink + business journal + issue occurrences
│   ├── issues/            # Error tracking (Sentry-as-Postgres): fingerprint-grouped issues
│   ├── metrics/           # Load metrics: /metrics Prometheus endpoint + console Load screen
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

Today it has one consumer: the Locust perf smokes (`scripts/smoke.py`, `make perf-smoke`)
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


#### Local Supabase endpoints

(from `supabase status`):

| Interface           | URL                    | Purpose                                                     |
| ------------------- | ---------------------- | ----------------------------------------------------------- |
| **Supabase Studio** | http://localhost:54323 | Web UI: tables, Auth, Storage, SQL editor                   |
| **Supabase API**    | http://localhost:54321 | PostgREST, Auth API, Storage API                            |
| **Postgres direct** | localhost:54322        | psql or any SQL client (user: `postgres`, pass: `postgres`) |
| **Mail catcher**    | http://localhost:54324 | Inbucket/Mailpit — captures all auth emails locally         |


#### `.env` vs `.env.test`


| File        | Used by                                 | Hosts                        |
| ----------- | --------------------------------------- | ---------------------------- |
| `.env`      | `docker compose` (app container)        | `host.docker.internal:543xx` |
| `.env.test` | `make test` / `make test-e2e` (on host) | `127.0.0.1:544xx`            |

`make env` generates `.env` (mapping the Supabase CLI output to `SUPABASE_API_URL`,
`SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `SUPABASE_DATABASE_USER_URL`,
`SUPABASE_DATABASE_ADMIN_URL`, with the asyncpg driver and `host.docker.internal` host).
`.env.test` is committed and uses `127.0.0.1`. It points at the checkout's test stack (543xx is
the dev stack, 544xx the test one — see Parallel work below).

Notes:

- **Front-end assets** — `static/` is gitignored; re-run `make install` after adding a
  Tailwind class (unused ones are purged) or bumping a `package.json` dependency.
- **`COOKIES_SECURE=false`** is required over plain HTTP. Otherwise session cookies get
  the `Secure` flag and are dropped on non-HTTPS, returning 401 on every authenticated
  request.
- **Migrations** — `supabase start` and `make db-reset` apply `supabase/migrations/`
  locally. `make migrate` (`supabase db push`) is for a linked **remote** project.
- **Browser for e2e** — `playwright install` downloads Google's Chrome for Testing. To drive a
  Chromium already on the machine instead, export `CHROMIUM_EXECUTABLE_PATH` (its binary, e.g.
  `/Applications/Chromium.app/Contents/MacOS/Chromium`) and `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`;
  `make test-e2e` and `make flakehunt` pass it to the driver, and the Playwright MCP reads the same
  path from `PLAYWRIGHT_MCP_EXECUTABLE_PATH` (`.claude/settings.local.json`). CI leaves both unset.
- **Python language server** — nothing to install: `pyright` is pinned in the dev group, so
  `make install` puts it in `.venv/`. The in-tree plugin `.claude/plugins/pyright-lsp/` points
  Claude Code at that binary; VS Code reaches the same engine through Pylance. Both read the
  `[tool.pyright]` block, which leaves type checking to `ty`.

### Parallel work: isolated worktrees

To develop several features in parallel without their data colliding — and so `make ci`
never wipes your `make dev` data — `make dev` and the tests never share a stack. `make dev`
runs on the local Supabase stack (543xx), where each git worktree gets its **own** Postgres
schema, Storage bucket and app port. Each checkout's tests run on a stack of their **own**,
`labase-<checkout>-test`, on the ports its `.env.test` names: 544xx for the main checkout, a
block derived from the name for a worktree. `auth.users` and the mail catcher belong to a
stack, so a test run never reaches another checkout's users. This is also what makes parallel
agent-driven development safe.

`make test-stack` starts it — idempotent, run by every test lane, ~30 s cold and ~600 MB with
Studio, analytics and realtime left out — and `make test-stack-rm` removes it with its volumes.

```bash
make worktree NAME=calendar     # creates worktrees/calendar
cd worktrees/calendar && make dev   # → its own port (e.g. http://localhost:8019)
make worktree-rm NAME=calendar  # removes worktree + schema + bucket
```

Per worktree `<name>`:

| Resource  | Dev (`make dev`)    | Test (`make ci`)                |
| --------- | ------------------- | ------------------------------- |
| Stack     | the dev stack       | `labase-<name>-test`            |
| API port  | 54321               | derived from name (54521-59421) |
| DB schema | `wt_<name>`         | `test_<pid>`                    |
| Bucket    | `org-files-<name>`  | `org-files-test-<pid>`          |
| App port  | derived from name   | in-process                      |
| Dev user  | `<name>@labase.dev` | —                               |

The schema is a structural clone of `public` (`scripts/provision_schema.py` — a `pg_dump`
of `public`, rewritten to the target schema, plus the Storage bucket/policies and a
per-schema signup trigger). On the dev stack, auth (GoTrue / `auth.users`) is shared by the
worktrees — the dev user is namespaced by email. A `node_modules` symlink and `uv sync` mean
a worktree needs no full reinstall. Tests run in a `test_<pid>` schema, named after that
`make` invocation's own pid so two runs started together in the same checkout never share one
— cloned from their own stack's `public` (`make provision-test`, run automatically by
`make test`). A schema outlives its own run so a failure stays inspectable; the next run to
provision one sweeps any other whose pid has since exited.

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
make upgrade      # Bump every Python dependency and re-pin (full pass: docs/upgrade.md)
make upgrade-base # Product clones: merge the latest base (see docs/upgrade-base.md)
make worktree NAME=x     # New git worktree with its own schema/bucket/port
make worktree-rm NAME=x  # Remove it (worktree + schema + bucket + test stack)
make test-stack   # This checkout's test stack, started if needed (every test lane runs it)
make test-stack-rm       # Remove it with its volumes, and those of worktrees deleted by hand

make install      # Supabase + uv sync + pre-commit + npm install + .env + npm run build

make lint         # ruff + import-linter + ty + pyright + biome + djlint + pip-audit, read-only
make fix          # ruff --fix + format + import-linter + ty + biome + djlint --reformat
make doctor       # local stack reachability AND latency (catches a wedged Docker proxy)

make test         # pytest unit/integration (generates coverage)
make test-e2e     # pytest-bdd browser driver + Playwright E2E
make perf-smoke   # Locust smoke over the generated API client (blocking thresholds)

make finalize     # js-build + fix + lint + test (run before committing)
make ci           # js-build + lint + test + test-e2e + perf-smoke + coverage-report, all steps run even if one fails
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
