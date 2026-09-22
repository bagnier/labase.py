## General


### Demo apps are disposable, the others loosely coupled

The base is a collection of self-contained apps (bounded
contexts): each owns its domain logic, routes, templates, tests and migrations, and can
be added, disabled, or deleted without touching the others. Boundaries are hard —
domain code never imports infrastructure; apps never import each other. The only
inter-app surfaces are each app's public contract and the event bus. These boundaries
are enforced by import-linter contracts.


### Every business endpoint has two faces

The same handler serves the JSON API and the
HTML UI — a full page, or an HTMX fragment for in-page updates — through content
negotiation. One implementation buys a documented REST API _and_ a server-rendered,
dynamic front end, with no separate frontend project and no JS build step.


### Integration is declarative

An app states everything it contributes in a single
mount call: its routes, sidebar entry, dashboard card, admin-console stats, tunable
settings, on/off switch, and starter data for new organizations. Reactions to other
apps' flows travel through typed events — the emitter never knows its subscribers, and
deleting an app removes every trace of it.


### Business events are facts, not sagas

A sensitive domain action is emitted as a typed,
immutable `BusinessEvent` and persisted to an append-only journal _transactionally_ with the
action — the fact commits iff the mutation does, with no exception: the emitter names that
transaction explicitly, and there is no second way to record a fact. **Only what happened is a
fact**: a refused attempt (a wrong password, a blocked last-owner change, a non-owner reaching an
owner-only route) changed nothing, so it is a structured log line, not a fact — visible in the
same console timeline, on its technical side. Each app declares the events it owns, and
`emit` refuses an unowned one. Reactions are durable and run off the journal _after_ commit, so a
producer never waits on — or fails from — a consumer; a reaction that finds its subject already
gone is a clean no-op, never a compensation. The emitter never names its subscribers.


### The admin console sees every app

Each app reports server-wide stats to the SaaS
console, declares its admin-tunable settings there, and can be switched on or off
(applied on restart) — a disabled app drops its routes, nav and dashboard card but 
keeps its console tile (and still reserves its URL slugs) so admins can re-enable it.
Beyond per-app stats, the console ships the operational screens: accounts (disable,
delete, impersonate — bannered and recorded), the unified **Timeline**, issues, the
**Tasks** screen (what the queue still owes, and a film strip of what it ran), load
metrics, and the runtime log level.


### The database enforces isolation and authorization

Row-level security, versioned as plain SQL
migrations, is the single source of truth for who sees what. Python never re-implements
isolation for authenticated access. A policy calls two kinds of helper: *isolation* (which org a
row belongs to), held by SQL alone, and *authorization* (which role may act on it), which the
route repeats — exactly, never stricter — so a refusal reads as a clean 403. Every authorization
rule is stated once and checked at both the database and the route. SQL also holds the
invariants, what must never become false whoever writes; decisions and derived values stay in
Python.


### Facts, traces, bugs: three records

Domain facts go to an append-only journal, machine traces to the
log sink, bugs to fingerprinted issues; the console's Timeline reads all three and correlates them
per user, org, request and entity. Only the journal is transactional — the rest never blocks, slows
or fails the action it observes.


### Tests are sincere

The same plain-language scenarios run twice — over real HTTP and
through a real browser — against a real database. Nothing business-critical is mocked;
unit tests may stub external edges to reach error paths. For browser testing, goto() or
fetch() should be treated as possible code smells since we want to follow links and to
submit forms.


### Multi-tenancy by default

Every account gets a personal organization at sign-up;
org data lives under `/{org_handle}/…`. Members read, owners write.

### The first to sign up is admin

Whoever signs up while the server has no admin becomes one — the first account, or the next one if
that account was gone before its bootstrap ran. They can then promote any other user as admin.


### One clock, one key, one style

Time comes from a single clock; identity from a single key
shape — every primary key is a time-ordered UUIDv7; styling from one component system (Tailwind +
daisyUI); markup is semantic and accessible.


### Invariants are types, not checks

A constraint the domain must uphold is expressed as
a constrained type (Pydantic `Literal`, a value object) wherever it can be, so the type
checker rejects a violation before a test has to.


### No magic number

A number that tunes behaviour — a batch size, a poll
interval, a retention window, a retry budget, a page length — is a setting, not a literal:
**technical** where a deploy owns it (env, read at boot), **live** where an admin does (console,
per-org overridable). A value inlined in a signature or frozen in a module constant is a knob
only a new release can turn. Three kinds of number are not that — a setting's own declared
default, a figure that *is* the thing (an HTTP status, an SVG dimension, a fingerprint's frame
count) and the domain's own rules — and everything else left in code is enumerated, never waved
away: the list is the distance to the sentence, and it only shrinks.


### `| None` means optional

Not _unknown_ — if no writer can produce a `None`, the annotation is
slack and every reader pays for it by tracing the writers itself. Not _not yet_ — a value bound
after construction is a lifecycle, and a lifecycle belongs in the constructor, or behind one
accessor that narrows it, never in each reader's type. The same rule runs down to the schema: a
column is `not null` wherever null is unreachable. A compensating `assert x is not None`, a
defensive `or {}` at every read, or a suppression added to tolerate either, is the sign the
annotation is wider than the truth.



## Architecture

### Each context splits its domain from its infrastructure

Organized by **bounded context**, each split into `domain/` (business logic,
framework-free) and `infra/` (router, repository, framework I/O):

```
HTTP request → infra/router.py → domain/service.py → infra/repository.py → DB / external service
```

### Routers own HTTP and nothing else

Routers own HTTP and nothing else — parsing, serialization, status codes; no business
logic, no direct DB access. Every business route answers three audiences from one
handler: **JSON** (`wants_json`), **HTMX fragment** (partial templates named `_*.html`),
or **full page** — the shared helpers in `apps/shared/http/` absorb the branching.

### Everything a context needs lives in it

Templates, tests, and BDD steps live with their context: `<context>/templates/`,
`<context>/tests/e2e/` (incl. API + browser driver mixins), `<context>/tests/e2e/steps.py`.
Shared layout sits in `apps/shared/templates/`, Gherkin `.feature` files in `features/`,
and shared E2E drivers in `tests/e2e/drivers/`.


## Integration — between apps, and with the admin console

### An app declares every surface it contributes

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


### A contract never exports a settings handle

Handlers declare the app's `TodoSettings`
dependency (`contract/current.py`) and get the request's effective values — org overrides
applied under `/{org_handle}`, server values elsewhere. Non-request code uses
`get_settings("todo")`, plus `.for_org(session, org_id)` when an org is in hand.


### Two collaboration objects, two shapes

Push (a fact happened) and pull (who contributes
to this?) are different animals, so they are different objects — `host.events` (the
`EventBus`) and `host.contribs` (the `Contribs` registry). Both key handlers by the Python
type they carry, so there are no magic strings and no shared imports.


### `emit` records a fact and does only that

`emit(event, session)` **persists** the `BusinessEvent` to the journal on
the session the caller names — atomic with the action, so the fact commits iff the mutation commits
— and does *only* that. The session is a required argument: durability is stated at the call site,
not inherited from whichever dependency the route happened to pick. It refuses an event no app
declared (each app `declare`s the events it owns at mount, so an emitted fact is always owned); no
reaction runs in-process. Durable **async** consumers registered with `on(...)` and run-everywhere
handlers registered with `spread(...)` are delivered by the event listener off the persisted journal
after commit (see Observability), so a producer never waits on — or fails from — a consumer.
Reactions treat the fact as immutable history: one that finds its subject already gone is a clean
no-op, never a compensation.


### An app may subscribe to its own business event

The bus decouples twice: in **space** — the emitter never names its reactions — and in **time** — 
the reaction runs after the producer's commit, in its own transaction. Only the first is about 
boundaries, so an app reacting to itself is legitimate exactly when it needs the second: `issues` 
alerts on its own `issues.opened` because a failing alert must never roll back the occurrence that 
recorded the failure. Otherwise it is a function call written the long way round.


### Signing in is one fact

A session delivered by a password, an OAuth round-trip, a passkey or a
mailed confirmation link is the same event — `auth.signed_in` — carrying *how* it was obtained
(`method`) and whether a second factor was cleared (`two_factor`) in its payload, not in its `kind`.
It is recorded at the moment the session is handed over, never before, so a sign-in a second factor
then refuses never happened — and no token stands in for it: once an account enrolled an
authenticator, `get_current_user` refuses its `aal1` tokens (the one a challenge relays, or a
passkey's), save under an impersonation vouched for by a live admin token. `set_auth_cookies` is the single place a session is delivered, and a
test over its call sites holds the rule: each one records a sign-in, except the named
*re-issues* (a token refresh, the restore of an admin's stashed session after an impersonation,
the aal2 session a confirmed authenticator enrolment hands back).

Technical error capture is *not* on the bus: an `ExceptionCaptured` (not a business fact) is fanned
out to its trackers by the capture drain with log-and-skip isolation, directly between the
`logs` and `issues` contexts (see Observability), so a failing tracker never worsens the
exception it tracks.


### A contribution is pulled, and a failing contributor is skipped

A registry of contribution providers (an extension point),
declared at mount and read synchronously on the request path — *not* events:

|                | `provide(query_type, fn)`                           | `collect(query)`                                                      |
| -------------- | --------------------------------------------------- | --------------------------------------------------------------------- |
| **Semantic**   | register a contributor for a query type             | pull / query — runs all providers, aggregates successful returns      |
| **On failure** | —                                                   | logs & skips the failing provider (a down app can't break the page)   |
| **Used for**   | dashboard/console cards, org nav, settings sections | `OverviewQuery`, `ConsoleOverviewQuery`, `OrgNavQuery`, `ApiKeyQuery` |


### Sign-up is a chain of durable reactions

The signup trigger records `UserCreated` on GoTrue's own transaction
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


### The dashboard collects one card per app


```
GET /{org}/ → contribs.collect(OverviewQuery)
  ← files, learning, todo, calendar, pages each return an Overview (icon, title, counts, recent items)
     one context failing does not break the dashboard
```


### Import downward, event upward

When one context reaches another, the dependency direction
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


## Observability


### The journal records what changed the domain

A sensitive domain action is a typed, frozen
`BusinessEvent`, its `kind` (`todo.ticked`, `organizations.renamed`) derived from an app prefix and
a verb, never hand-written. `emit(event, session)` appends it to `business_events` through one
SECURITY DEFINER writer, on the caller's own transaction — the fact commits iff the mutation does,
and no PostgREST client can forge one. Reads are RLS-scoped; the **profile** and
**`/{org}/dashboard`** render them as a feed. This is the one record the base lets sit on a
request's critical path. A fact has no severity: it happened. `emit` logs nothing of its own, so
an action shows up once, not twice.


### The log sink traces the machinery off the request's path

`structlog.get_logger(__name__)`, dotted
`snake_case` names with kwargs, never f-strings or `print`. Every line carries its logger, and that
name is the `app` axis the Timeline reads. Rendered to stdout (JSON in production, pretty console
in dev) and appended to `log_lines` — one Postgres table the whole deployment shares, so the
Timeline shows every instance's lines rather than whichever one answered the page. The request
path only enqueues (a bounded deque); a background `LogDrain` batches to the table, so a dropped
line never costs the action that wrote it. Volume is what a log table lives or dies on, so the
table is `UNLOGGED` (no WAL at all — crash recovery empties it, which is the right trade for the
one kind of data whose durable copy is already on stdout) and partitioned by day, and the write is
one multi-row insert per drain with `synchronous_commit` off. Retention rolls those partitions
(`timeline.retention_days`): a day past the window leaves as a `DROP`, instant and leaving nothing
for VACUUM. When Postgres itself is what is down the batch falls back to per-day files — a database 
outage is exactly when an operator still wants the log — with the outage said once on each transition 
rather than going quiet. The level (`timeline.log_level`) starts at `INFO`, which is the floor since
nothing writes below it, and an admin can raise it to `WARNING` or `ERROR` to quiet an instance —
live, from the console.


### A line says what no other record says

A line says what no other record says already: the exchange is stated once
by `request.finished`, a domain action once by its fact, and a line restating either says the same
thing twice. Two levels carry the rest. `info` is **a point of surprise** — never the happy path:
an outage that ended, an actor gone mid-flight, a dependency answering no, a request that cost
forty queries. `warning` is **what the code could not carry through and absorbed** — the breakage
taken on the chin (a retry, a fallback, a dropped batch) and the attempt refused (a wrong password,
a non-owner on an owner-only route) alike; neither ran to completion, both were answered with
something. `exception` is a bug, and that is the whole vocabulary: there is no `debug` tier, since
the one thing a per-statement firehose bought is written as the surprise it is (`db.heavy_request`,
when a request's query count or DB time crosses its tunable threshold). A healthy server at rest
writes nothing at all, which is what makes its silence readable — and AST tests hold that rule the
way they already hold the naming one.


### Nothing escapes the log chain

The libraries' stdlib `logging` joins the same chain at `WARNING` and above
— a library is there for its degradations, not its chatter — and so do `warnings.warn` and the four
exits an exception can take without meeting an `except`: a bare task, a thread, `__del__`, the
interpreter on its way out. A broad `except Exception` that logs carries its `exc_info`, so the
stack survives even where the failure is handled rather than tracked (an AST test holds the rule).
Every served request leaves one `request.finished` line — including one whose handler raised —
whose *level* carries the outcome: `error` on a 5xx, `warning` on a dead link of ours, `info`
otherwise; what the browser fetched by itself leaves nothing unless it 5xx'd. The request
middlewares are plain ASGI, not `BaseHTTPMiddleware`, which is what lets that line name the user
and org the request bound below it.


### A bug is an issue with a lifecycle

Every `log.exception` is teed to a bounded queue and folded,
by stack fingerprint, into an `Issue` that opens, resolves, and regresses on a later version. Each
sighting is an `Occurrence` carrying the JSONB context that pivots back to the log sink — one per
failure, whatever else logs the same exception on its way out. The drain fans out with log-and-skip
isolation, so a failing tracker never worsens what it tracks, and drains once more when the process
is asked to stop. Opening and regressing are themselves facts (`issues.opened`, `issues.regressed`)
naming the request that tripped them, never its user: the journal is readable by whoever it names,
and an internal issue has no business in someone's activity feed.


### A broken dependency is a bug, a refusal is not

A call outside the process fails two ways that look alike: the dependency
*answered no* — a 4xx, a wrong password, an expired link — which is an ordinary outcome at `info`;
or it is *broken* — unreachable, a 5xx, a client raising something of its own — which is an issue.
One verdict (`apps/shared/logs/dependency.py`) for GoTrue, Postgres and Storage alike, so
an outage does not fill the issues screen or stay silent depending on the module it was reached
through — and a status the client kept as text counts, since Storage sends its own that way. SMTP
is the one reached through the queue instead: a send that keeps failing retries, then parks, and
the park is what opens the issue.


### A failure that repeats is one bug

The five lifespan workers catch everything, so one bad tick
never ends a loop — which is exactly how a task worker that stopped claiming, or a listener that
stopped delivering, used to leave nothing but a `warning`. They tick once a second, so the level
follows the *transition*, not the tick (`apps/shared/logs/loop.py`): falling over opens
one issue, the ticks after it warn with how many, coming back says what the outage cost. The
readiness probe is on the same verdict, being polled the same way. A bare `log.error` is
deliberately not the seam — `request.finished` writes one on every 5xx to state the outcome — so a
site that means *this is a bug* raises an exception of its own to be seen.


### The Timeline reads the journal, the log sink and the issues

`apps/timeline` writes nothing: its console screen merges the
journal (`business`), the log sink (`logs`) and issue occurrences (`issue`) into one view,
filterable by those three sources and
correlated on four keys — **user**, **org**, **request**, and the concerned **entity**. A fact
carries them in its own columns, plus the handle, org name and the **subject's own name** as they
read *then*, so a deletion or RLS cannot hide _who_, _where_ and _what_ later; those pinned names
are shown on the row and are what free text searches, alongside the payload. Lines and occurrences
inherit the ids from contextvars bound by the request / auth / org-scope layers. Only a fact knows
an entity, hence the per-entity filter narrows to the journal alone. Sorting is newest-first over
the whole window; any other column orders the loaded page only — each source is asked for its own
newest rows — and the screen says so rather than pass a sample off as an ordering.


### Load metrics belong to their app alone

`apps/metrics` owns the counter outright. The request middleware only *offers*
what it measured — `on_request_measured`, the same shape as the capture seam feeding `apps/issues`
— so the app subscribes at mount and shared never names it. Switch the app off and the offer finds
nobody; delete it and nothing counts anywhere, which is the promise every app is meant to keep.
What it does with the exchanges is its own: a Prometheus `/metrics` endpoint, per-minute rows, the
console **Load** screen, and a daily rollup that downsamples minute → hour and applies retention.


## Conventions


### Three sessions, and RLS by default

Each context's FastAPI dependencies live in its own
`contract/current.py` — `CurrentUser` / `OptionalCurrentUser` (auth), `CurrentOrg`,
`CurrentMembership`, `CurrentOwnerMembership` (organizations, clean `403` for
non-owners). Three DB session dependencies: `RlsSession` (default — RLS enforced),
`get_user_session` (raw), `AdminSession` (BYPASSRLS — reserved for event handlers,
console queries, and anonymous public surfaces such as share-token downloads, where no
JWT exists and checks are explicit). `RlsSession` runs on `app_rls`, a member of `authenticated`
that alone may enqueue a task or record a fact: PostgREST serves a JWT on `authenticated`
itself, so what is granted there is open to any account. An anonymous caller gets `app_rls` with
claims naming nobody. What must be read before or outside an identity — resolving an API key,
whether an account enrolled a second factor, an invitation by its token, an org's public pages
for a visitor outside it — goes through a `SECURITY DEFINER` function executable by `app_rls`
alone, so the caller is resolved and the public pages served without a BYPASSRLS session.


### A GET never delivers a session

Email/password with mailed confirmation (resend on blocked
unconfirmed sign-ins, forgot/reset flow), OAuth social sign-in (Google, GitHub — GoTrue
PKCE), TOTP two-factor, and passkeys (WebAuthn). Email change with mailed confirmation
and self-serve account deletion are settings-gated (`profile.*_enabled`). A mailed link opens a
page whose button posts its token back: a GET never delivers a session. Sign-in and sign-up
forward the visitor's address to GoTrue as `Sb-Forwarded-For`, so its per-IP limit sees visitors
rather than the instance (docs/production.md).


### Deferred work rides a durable Postgres queue

Deferred work rides the durable Postgres task queue
(`apps/shared/queue.py`): `enqueue()` writes through the caller's session, so a task
exists iff the business transaction commits (outbox semantics); a per-process
`TaskWorker` claims with `FOR UPDATE SKIP LOCKED` (safe across instances), retries with
backoff, then parks the failure — where the **Tasks** screen (`apps/tasks`) lists it
alongside what is late or being retried, since the issue a park opens says there is a bug
and this says what did not run. Recurring jobs (purges, rollups) re-enqueue
themselves on completion. Transactional email goes the same way: `enqueue_email()`
behind the `Mailer` port (`apps/shared/email.py` — SMTP, caught by Mailpit in dev).
Durable async event delivery rides the same queue: the event listener (`apps/shared/events/listener.py`,
NOTIFY-woken, polling as a net) reads the `business_events` log and enqueues one task per
`on` consumer, so a fact's reactions get the queue's retry, parking and at-least-once safety.
It claims what it dispatches in the transaction that stamps it, so N instances never fan one
fact out twice.


### CSRF needs no token, and the rate limiter fails open

Cross-site mutations are rejected by a `Sec-Fetch-Site` middleware
(CSRF protection without tokens); rate limiting counts against a shared Postgres store
(`apps/shared/http/limiter.py`), so limits hold across instances. The limiter fails open: a
store it cannot reach lets the request through, because rate limiting must never be what takes
an endpoint down — and it says so through the dependency verdict, since failing open quietly is
how a limiter stays off for good.


### One set of helpers branches JSON, fragment and page

`wants_json(request)` / `wants_full_page(request)` and the
`render_list(...)` helper in `apps/shared/http/` centralize the JSON / fragment / page
branching. Fragments are standalone valid markup (they're swapped into the live DOM).


### A form is JSON at the door

The request side negotiates nothing: the innermost middleware (`apps/shared/http/form.py`)
re-encodes a urlencoded form as JSON before routing, so every mutation declares one Pydantic body
that FastAPI validates and documents, and nothing reads `request.form()` by hand — a multipart
upload passes through untouched. Every JSON answer names its model the same way
(`json_and_html(Model)`, `response_model=`), and the API lane validates each answer it receives
against the schema its route declares (`tests/e2e/drivers/conformance.py`): the OpenAPI document
is held by the scenarios that drive the routes, not by a promise.


### A page's context is assembled from slices its apps own

A full page's context is assembled from _slices_, each owned by
the app that knows it. Apps register a provider at mount time with declared, prefixed
keys (collisions rejected at startup); the ownerless collector in `apps/shared/integration/fullpage.py`
merges them — called explicitly, never injected silently.


### `clock.now()` is the only clock

`clock.now()` is the single source of time. Never call `datetime.now()`.


### Every key is a UUIDv7, every token a UUIDv4

Every table's primary key is a time-ordered **UUIDv7**, minted by the ORM where Python
writes and by the database where it does not — a trigger, a raw insert, the journal's own writer.
Globally unique with no shared sequence, so instances never coordinate, and ordered by the instant
they were minted, which is what lets an append-only trail page on its key rather than carry a
cursor of its own. That ordering is exact within one minter; across the two it is only as good as
the agreement between the app's clock and the database's. Because every key is a uuid, a business
event's `entity_id` correlates entities by their stable pk, never a renameable handle. Security
tokens are the deliberate exception — they stay random **UUIDv4** (unguessable, no
embedded timestamp).


### daisyUI components, never re-spelled utility chains

daisyUI 5 is the component system (`btn`, `card`, `input`, `alert`,
`badge`, `stat`, `menu`…). Project-specific component classes live in
`@layer components` in `static/css/input.css` (`list-panel`, `md-body`). Reuse
components instead of re-spelling utility chains; keep one-off layout inline. Icons are
Phosphor. Markup uses real landmarks, labelled controls, `aria-hidden` on decorative
icons, visible focus rings.


### Each scenario runs isolated, on both drivers

Both E2E drivers share a substrate in `tests/e2e/drivers/` that each
context's feature mixins extend. Every actor in a scenario gets an isolated session —
its own httpx client, or its own browser context with a distinct cookie jar — so
multi-user scenarios never bleed auth state. The API driver wraps each scenario in a
rolled-back transaction; the browser driver runs an in-process Hypercorn server and
truncates app tables between scenarios. The browser driver navigates like a human:
entry point, then links and forms — no deep URLs.


### Assert the settled DOM, never wait on time

Assert DOM state with `expect(...)` (auto-retries to the settled
state), never `assert locator.is_visible()` (a snapshot — flakes the moment an HTMX swap
is mid-flight). `wait_for_load_state("networkidle")` and `wait_for_timeout(ms)` are banned
as state waits. Reruns are opt-in and justified per named suite; everything else is strict,
zero rerun.
