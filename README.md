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
   a durable task queue, error tracking, load metrics and rate limiting — plain
   Postgres tables, no new infrastructure. Fulltext search, caching and document
   storage are next.

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
are enforced by import-linter contracts.

**Every business endpoint has two faces.** The same handler serves the JSON API and the
HTML UI — a full page, or an HTMX fragment for in-page updates — through content
negotiation. One implementation buys a documented REST API _and_ a server-rendered,
dynamic front end, with no separate frontend project and no JS build step.

**Integration is declarative.** An app states everything it contributes in a single
mount call: its routes, sidebar entry, dashboard card, admin-console stats, tunable
settings, on/off switch, and starter data for new organizations. Reactions to other
apps' flows travel through typed events — the emitter never knows its subscribers, and
deleting an app removes every trace of it.

**Business events are facts, not sagas.** A sensitive domain action is emitted as a typed,
immutable `BusinessEvent` and persisted to an append-only journal _transactionally_ with the
action — the fact commits iff the mutation does, with no exception: the emitter names that
transaction explicitly, and there is no second way to record a fact. **Only what happened is a
fact**: a refused attempt (a wrong password, a blocked last-owner change, a non-owner reaching an
owner-only route) changed nothing, so it is a structured log line, not a fact — visible in the
same console timeline, on its technical side. Each app declares the events it owns, and
`emit` refuses an unowned one. Reactions are durable and run off the journal _after_ commit, so a
producer never waits on — or fails from — a consumer; a reaction that finds its subject already
gone is a clean no-op, never a compensation. The emitter never names its subscribers.

**The admin console sees every app.** Each app reports server-wide stats to the SaaS
console, declares its admin-tunable settings there, and can be switched on or off
(applied on restart) — a disabled app drops its routes, nav and dashboard card but 
keeps its console tile (and still reserves its URL slugs) so admins can re-enable it.
Beyond per-app stats, the console ships the operational screens: accounts (disable,
delete, impersonate — bannered and recorded), the unified **Timeline**, error issues,
load metrics, and the runtime firehose level.

**The database enforces isolation.** Row-level security, versioned as plain SQL
migrations, is the single source of truth for who sees what. Python never re-implements
isolation for authenticated access.

**Observability is built in.** Domain facts go to an append-only journal, machine traces to the
firehose, bugs to fingerprinted issues; the console's Timeline reads all three and correlates them
per user, org, request and entity. Only the journal is transactional — the rest never blocks, slows
or fails the action it observes.

**Tests are sincere.** The same plain-language scenarios run twice — over real HTTP and
through a real browser — against a real database. Nothing business-critical is mocked;
unit tests may stub external edges to reach error paths. For browser testing, goto() or
fetch() should be treated as possible code smells since we want to follow links and to
submit forms.

**Multi-tenancy by default.** Every account gets a personal organization at sign-up;
org data lives under `/{org_handle}/…`. Members read, owners write.

**First signed-up user is admin** and can then promote any other user as admin.

**One source of truth for the rest.** Time comes from a single clock; identity from a single key
shape — every primary key is a time-ordered UUIDv7; styling from one component system (Tailwind +
daisyUI); markup is semantic and accessible.

**Invariants are types, not checks.** A constraint the domain must uphold is expressed as
a constrained type (Pydantic `Literal`, a value object) wherever it can be, so the type
checker rejects a violation before a test has to.

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
| **Biome**                   | JS + CSS + JSON linting/formatting (`biome.json`)                                |
| **djlint**                  | Jinja2 template linting (configured in `pyproject.toml`)                         |
| **sqlfluff**                | SQL migration linting — lint-light, no reformat (`scripts/.sqlfluff`, Postgres)  |
| **gherkin-lint**            | BDD `.feature` structure linting (`scripts/.gherkin-lintrc`)                     |
| **yamllint**                | YAML linting (`scripts/.yamllint`)                                              |
| **validate-pyproject**      | `pyproject.toml` schema validation                                              |
| **zizmor**                  | GitHub Actions security linting (`.github/zizmor.yml`)                           |
| **droast**                  | Dockerfile linting — self-contained GitHub Action in CI (`.github/workflows/`)   |
| **ty**                      | Type checking (Astral, Rust)                                                     |
| **import-linter**           | Architecture boundaries between apps (contracts in `pyproject.toml`)             |
| **pip-audit**               | Dependency vulnerability audit                                                   |
| **pre-commit**              | Git hooks — `ruff --fix`, `ruff format`, talisman on staged files                |
| **pytest + pytest-asyncio** | Unit and integration tests                                                       |
| **pytest-bdd + Playwright** | Functional BDD tests (Gherkin) — same scenarios run against API and real browser |
| **pytest-cov**              | Code coverage (generates `.cache/cov/coverage.xml` for VS Code)                  |

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
root (`apps/main.py`) mounts them in phase order — catch-all routes (e.g. the org
`/{slug}`) sort last so a fixed route is never shadowed; no context knows about another.
At mount time, an app declares **every surface it contributes**:

| Surface           | Declared via                    | Shows up as                                                    |
| ----------------- | ------------------------------- | -------------------------------------------------------------- |
| Routes            | `host.app.include_router(...)`  | its pages and JSON API                                         |
| Sidebar           | `host.register_nav(...)`        | a global nav entry (per-org via `OrgNavQuery`)                 |
| Org dashboard     | handling `OverviewQuery`        | a card on `/{org}/` with counts + recent items                 |
| **Admin console** | handling `ConsoleOverviewQuery` | server-wide stats in the SaaS console                          |
| **Settings**      | `host.register_settings(...)`   | admin-tunable values, per-org overridable, live-reloaded       |
| Feature switch    | a declared on/off setting       | on/off toggle; disabled drops routes & nav, keeps console tile |
| Seeding           | handling `OrgCreated`           | starter data for each new org                                  |
| URL safety        | `host.reserve(...)`             | path segments no org handle can shadow                         |

Because every surface is registered rather than hardcoded, **deleting an app removes its
nav entry, dashboard card, console stat and seeds automatically** — this is what makes
the demo apps disposable.

**A contract never exports a settings handle.** Handlers declare the app's `TodoSettings`
dependency (`contract/current.py`) and get the request's effective values — org overrides
applied under `/{org_handle}`, server values elsewhere. Non-request code uses
`get_settings("todo")`, plus `.for_org(session, org_id)` when an org is in hand.

**Two collaboration objects, two shapes.** Push (a fact happened) and pull (who contributes
to this?) are different animals, so they are different objects — `host.events` (the
`EventBus`) and `host.contribs` (the `Contribs` registry). Both key handlers by the Python
type they carry, so there are no magic strings and no shared imports.

**`host.events` — push.** `emit(event, session)` **persists** the `BusinessEvent` to the journal on
the session the caller names — atomic with the action, so the fact commits iff the mutation commits
— and does *only* that. The session is a required argument: durability is stated at the call site,
not inherited from whichever dependency the route happened to pick. It refuses an event no app
declared (each app `declare`s the events it owns at mount, so an emitted fact is always owned); no
reaction runs in-process. Durable **async** consumers registered with `on(...)` and run-everywhere
handlers registered with `spread(...)` are delivered by the event listener off the persisted journal
after commit (see Observability), so a producer never waits on — or fails from — a consumer.
Reactions treat the fact as immutable history: one that finds its subject already gone is a clean
no-op, never a compensation.

**Signing in is one fact.** A session delivered by a password, an OAuth round-trip, a passkey or a
mailed confirmation link is the same event — `auth.signed_in` — carrying *how* it was obtained
(`method`) and whether a second factor was cleared (`two_factor`) in its payload, not in its `kind`.
It is recorded at the moment the session is handed over, never before, so a sign-in a second factor
then refuses never happened. `set_auth_cookies` is the single place a session is delivered, and a
test over its call sites holds the rule: each one records a sign-in, except the two named
*re-issues* (a token refresh, the restore of an admin's stashed session after an impersonation).

Technical error capture is *not* on the bus: an `ExceptionCaptured` (not a business fact) is fanned
out to its trackers by the capture drain with log-and-skip isolation, directly between the
`observability` and `issues` contexts (see Observability), so a failing tracker never worsens the
error it tracks.

**`host.contribs` — pull.** A registry of contribution providers (an extension point),
declared at mount and read synchronously on the request path — *not* events:

|                | `provide(query_type, fn)`                           | `collect(query)`                                                      |
| -------------- | --------------------------------------------------- | --------------------------------------------------------------------- |
| **Semantic**   | register a contributor for a query type             | pull / query — runs all providers, aggregates successful returns      |
| **On failure** | —                                                   | logs & skips the failing provider (a down app can't break the page)   |
| **Used for**   | dashboard/console cards, org nav, settings sections | `OverviewQuery`, `ConsoleOverviewQuery`, `OrgNavQuery`, `ApiKeyQuery` |

**Sign-up event chain:** the signup trigger records `UserCreated` on GoTrue's own transaction
(atomic with the account); a **durable async consumer** then creates the user's personal org and
persists `OrgCreated`, whose welcome seeders are themselves durable async consumers — every reaction
delivered by the event listener off the journal (retried and parked on failure, never on the signup's
critical path).

```
signup → trigger records UserCreated → organizations: creates personal org → emit(OrgCreated) ─┐
                                                                                      │  (persisted)
  event listener reads the log, fans OrgCreated out to each seeder ─────────────────────┘
      → files:    seeds welcome.txt          → todo:     seeds 3 welcome todos
      → learning: seeds Welcome deck         → calendar: seeds a welcome event
      → pages:    seeds a public Welcome page (the base's own pitch, in the public nav)
```

**Dashboard query:**

```
GET /{org}/ → contribs.collect(OverviewQuery)
  ← files, learning, todo, calendar, pages each return an Overview (icon, title, counts, recent items)
     one context failing does not break the dashboard
```

**Import downward, event upward.** When one context reaches another, the dependency direction
picks the mechanism:

- **Direct contract import** when the call points *down* to a foundation every feature may
  depend on — `auth.contract` (identity: `CurrentUser`, `RlsSession`, `AuthenticatedUser`),
  `organizations.contract` (org scoping: `CurrentOrg`, `app_settings`, `ORG_PREFIX`), and
  `console.contract.overviews` (the `ConsoleOverviewQuery` type). These are typed, statically
  checked and navigable — you *want* the coupling explicit.
- **Event or contribution** when the call would point *up*, from a foundation into features it
  must not name: `organizations` emits `OrgCreated` instead of importing calendar/todo/files to
  seed them; `auth` resolves a bearer token with `contribs.collect(ApiKeyQuery)` instead of
  importing `api_keys`. The registry inverts the dependency so the foundation stays ignorant of
  its consumers.

Rule of thumb: a feature importing a foundation is healthy; a foundation importing a feature is
a smell — reach for an event (an import-linter contract enforces the one-way edges, e.g. auth
never imports organizations). Runtime publishers/collectors reach the process-wide `bus`
singleton (`apps.shared.events.bus`) directly; `host.events` is that same bus, wired at mount.

### Observability

**The journal — what changed the domain.** A sensitive domain action is a typed, frozen
`BusinessEvent`, its `kind` (`todo.ticked`, `organizations.renamed`) derived from an app prefix and
a verb, never hand-written. `emit(event, session)` appends it to `business_events` through one
SECURITY DEFINER writer, on the caller's own transaction — the fact commits iff the mutation does,
and no PostgREST client can forge one. Reads are RLS-scoped; the **profile** and
**`/{org}/dashboard`** render them as a feed. This is the one record the base lets sit on a
request's critical path. A fact has no severity: it happened. `emit` logs nothing of its own, so
an action shows up once, not twice.

**The firehose — a trace of the machinery.** `structlog.get_logger("labase.<context>.<subject>")`,
dotted `snake_case` names with kwargs, never f-strings or `print`. Rendered to stdout (JSON in
production, pretty console in dev) and teed to per-day JSON Lines files, which is what lets a reader
scroll a recent window back. The request path only enqueues; a background `FirehoseWriter` batches
to disk, so a dropped line never costs the action that wrote it. Its level (`timeline.log_level`) is
admin-tunable from the console and applies live, no restart.

**Issues — a bug, with a lifecycle.** Every `log.exception` is teed to a bounded queue and folded,
by stack fingerprint, into an `Issue` that opens, resolves, and regresses on a later version. Each
sighting is an `Occurrence` carrying the JSONB context that pivots back to the firehose. The drain
fans out with log-and-skip isolation, so a failing tracker never worsens what it tracks. Opening and
regressing are themselves facts (`issues.opened`, `issues.regressed`).

**The Timeline reads all three.** `apps/timeline` writes nothing: its console screen merges the
journal, the firehose window and issue occurrences into one view, filterable by source and
correlated on four keys — **user**, **org**, **request**, and the concerned **entity**. A fact
carries them in its own columns, plus the handle and org name as they read *then*, so a deletion or
RLS cannot hide _who_ and _where_ later; lines and occurrences inherit them from contextvars bound
by the request / auth / org-scope layers. Only a fact knows an entity, hence the per-entity filter
narrows to the journal alone.

**Load metrics.** Every request feeds a shared accumulator, exposed as a Prometheus `/metrics`
endpoint and persisted per minute by `apps/metrics`; the console **Load** screen graphs it, and a
daily rollup downsamples minute → hour and applies retention.

### Conventions

**Auth & sessions.** Each context's FastAPI dependencies live in its own
`contract/current.py` — `CurrentUser` / `OptionalCurrentUser` (auth), `CurrentOrg`,
`CurrentMembership`, `CurrentOwnerMembership` (organizations, clean `403` for
non-owners). Three DB session dependencies: `RlsSession` (default — RLS enforced),
`get_user_session` (raw), `AdminSession` (BYPASSRLS — reserved for event handlers,
console queries, and anonymous public surfaces such as share-token downloads, where no
JWT exists and checks are explicit).

**Sign-in surface.** Email/password with mailed confirmation (resend on blocked
unconfirmed sign-ins, forgot/reset flow), OAuth social sign-in (Google, GitHub — GoTrue
PKCE), TOTP two-factor, and passkeys (WebAuthn). Email change with mailed confirmation
and self-serve account deletion are settings-gated (`profile.*_enabled`).

**Background work.** Deferred work rides the durable Postgres task queue
(`apps/shared/queue.py`): `enqueue()` writes through the caller's session, so a task
exists iff the business transaction commits (outbox semantics); a per-process
`TaskWorker` claims with `FOR UPDATE SKIP LOCKED` (safe across instances), retries with
backoff, then parks failures for inspection. Recurring jobs (purges, rollups) re-enqueue
themselves on completion. Transactional email goes the same way: `enqueue_email()`
behind the `Mailer` port (`apps/shared/email.py` — SMTP, caught by Mailpit in dev).
Durable async event delivery rides the same queue: the event listener (`apps/shared/events/listener.py`,
NOTIFY-woken, polling as a net) reads the `business_events` log and enqueues one task per
`on` consumer, so a fact's reactions get the queue's retry, parking and at-least-once safety.

**HTTP security.** Cross-site mutations are rejected by a `Sec-Fetch-Site` middleware
(CSRF protection without tokens); rate limiting counts against a shared Postgres store
(`apps/shared/http/limiter.py`), so limits hold across instances.

**Content negotiation.** `wants_json(request)` / `wants_full_page(request)` and the
`render_list(...)` helper in `apps/shared/http/` centralize the JSON / fragment / page
branching. Fragments are standalone valid markup (they're swapped into the live DOM).

**Page composition.** A full page's context is assembled from _slices_, each owned by
the app that knows it. Apps register a provider at mount time with declared, prefixed
keys (collisions rejected at startup); the ownerless collector in `apps/shared/page.py`
merges them — called explicitly, never injected silently.

**Time.** `clock.now()` is the single source of time. Never call `datetime.now()`.

**Identity.** Every table's primary key is a time-ordered **UUIDv7** — the `UUIDPk` mixin
(`default=uuid.uuid7`, Python 3.14 stdlib) on the ORM write path, mirrored by a `public.uuidv7()`
column default in SQL for raw / PostgREST inserts. Globally unique with no shared sequence (safe
across instances) *and* monotonic, so the append-only stores use a pk as a cursor: the event listener
claims/scans `business_events.id`, the issues detail pages `issue_occurrences.id`. Because every key is a
uuid, a business event's `entity_id` correlates entities by their stable pk, never a renameable
handle. Security tokens are the deliberate exception — they stay random **UUIDv4** (unguessable, no
embedded timestamp).

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

**Anti-flake e2e.** Assert DOM state with `expect(...)` (auto-retries to the settled
state), never `assert locator.is_visible()` (a snapshot — flakes the moment an HTMX swap
is mid-flight). `wait_for_load_state("networkidle")` and `wait_for_timeout(ms)` are banned
as state waits. Reruns are opt-in and justified per named suite; everything else is strict,
zero rerun.

### Structure

Every bounded context follows the same layout — `domain/` (models, service), `infra/`
(router, repository), `templates/`, `tests/`, and an optional `contract/` (its public
inter-app surface). One top-level module forms the composition root — the only place
allowed to know several contexts at once: `main.py`.

```
labase.py/
├── apps/
│   ├── main.py            # FastAPI app, mounts every context in phase order (catch-alls last)
│   ├── shared/            # Cross-context infra: events/ (types, catalog, wiring, bus, repository, listener),
│   │                      #   Contribs (contribs.py), Host (host.py), task queue (queue.py),
│   │                      #   Mailer (email.py),
│   │                      #   contract/integration.py (middleware/CORS/static),
│   │                      #   persistence, http, observability, templates/
│   ├── auth/              # Authentication — current user, RLS sessions, cookies
│   ├── api_keys/          # Per-org machine credentials for the JSON API (Bearer)
│   ├── organizations/     # Multi-tenant orgs, memberships, invitations
│   ├── profile/           # User profile
│   ├── pages/             # Per-org Markdown pages with draft/members/public visibility + nav
│   ├── console/           # SaaS admin console — server-wide stats, settings, admins, appearance
│   ├── timeline/          # The unified read view: firehose + business journal + issue occurrences
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
