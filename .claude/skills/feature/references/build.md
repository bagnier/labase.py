# Phase 4 — Build (test-driven, strictly per scenario)

For **each scenario**, run the cycle below in order before moving to the next. Run
`make test` after each sub-step.

## Per-scenario cycle

### a. Step definitions (`apps/<module>/tests/e2e/steps.py`)

- Add missing `@given` / `@when` / `@then`. Steps are **driver-agnostic**: they only call
  methods on `driver`.
- A step needing a new driver method → add a `NotImplementedError` stub first.
- For a brand-new context: create `apps/<module>/tests/e2e/steps.py`, register it in the
  `pytest_plugins` list in **`tests/plugin.py`** (there is no root `conftest.py`), and add
  `apps/<module>/tests/e2e/test_scenarios.py` with
  `scenarios("../../../../features/<name>.feature")`.
- `make test` → the scenario must fail with `NotImplementedError`, not a missing-step error.

### b. Drivers (`apps/<module>/tests/e2e/driver_mixin_{api,browser}.py`)

- Implement the new methods on **both** mixins. Export them from
  `apps/<module>/tests/e2e/__init__.py` and compose them into `ApiDriver` / `BrowserDriver`
  in `tests/e2e/drivers/{api,browser}.py`. (There is no `protocols.py`.)
- If a brand-new driver substrate is needed (email, queue…), create it without asking.
- `make test` → the scenario must fail with an application error (404, missing route…), not a
  driver error.

**Driver rules specific to this project (not guessable):**

- **Isolate sessions per actor.** A multi-actor scenario (owner + member + visitor) must never
  share a session. Act as a user via `self.client_for(email)` (API — scoped httpx client) and
  `self.page_for(email)` (browser — isolated Playwright context with its own cookies/auth),
  **not** the global `self.client` / `self.page`. The `VISITOR` sentinel stays unauthenticated.
  Sources: `tests/e2e/drivers/api_base.py`, `tests/e2e/drivers/browser_base.py`; multi-actor
  example: `apps/organizations/tests/e2e/driver_mixin_api.py`.
- **Browser driver navigates like a human.** Follow the UI's links and submit its forms — no
  direct calls, no hand-built URLs. Do **not** `page.goto(<deep-url>)` to reach a state: start
  from an entry point and **click** your way there (a `goto` to the root entry point is the
  only tolerated one). This keeps the tested links/forms real and wired. The API mixin, by
  contrast, hits endpoints directly — that's expected.

### c. Application code (`apps/<module>/`)

Implement domain logic first (`domain/`), then infra (`infra/`).
`make test` → **the scenario must pass before moving to the next one.**

---

## Module layout

```
apps/<module>/
  domain/    models.py (SQLAlchemy ORM + Pydantic DTOs), service.py (rules, pure async),
             repository.py (Protocol), exceptions.py
  infra/     repository.py (SQLAlchemy impl, extends BaseRepository), router.py (FastAPI),
             context.py (Depends resolvers)
  contract/  integration.py (mount(host)), current.py (re-exported Depends),
             queries.py (cross-app read functions), events.py (event dataclasses)
  templates/<module>/   Jinja2 + HTMX
  tests/e2e/ steps.py, driver_mixin_api.py, driver_mixin_browser.py,
             __init__.py (exports the two mixins), test_scenarios.py
```

Request flow: `infra/router.py → domain/service.py → infra/repository.py → DB`.

## Cross-app contract boundary

An app imports **only** from another app's `contract/`, never its `domain/` or `infra/`.

```
✅  from apps.organizations.contract.queries import org_by_handle
✅  from apps.organizations.contract.current import CurrentOrg
❌  from apps.organizations.infra.repository import ...
❌  from apps.pages.domain.models import PageVisibility
```

Expose what other apps need via `contract/current.py` (dependencies), `contract/queries.py`
(read-only functions returning DTOs, not ORM rows), and `contract/events.py`.

## Decoupling: two mechanisms, two shapes

Push (a fact happened) and pull (who contributes to this?) are different animals, so they are
different objects — `host.events` (`apps/shared/events/`) and `host.contribs`
(`apps/shared/integration/contribs.py`). Both key handlers by the Python type they carry.

| Primitive | Semantics | On failure | Use for |
|-----------|-----------|------------|---------|
| `await events.emit(event, session)` | persists the fact to the trail on the session you name — runs no handler | raises; the fact rolls back with the caller's transaction | `TodoCreated`, `OrganizationCreated` |
| `host.events.on(Event, handler, name=…, app=…)` | durable, exactly-once consumer, run by the listener off the trail after commit | retried, then parked; the producer never sees it | welcome seeding, counters, alerts |
| `host.events.spread(Event, handler)` | run-everywhere handler, replayed per instance | logged and skipped | config reload (`SettingsChanged`) |
| `await contribs.collect(query)` | runs every provider, aggregates the successes | logs and skips the failing provider | `OverviewQuery`, `ConsoleOverviewQuery` |

Defining a fact:

- a frozen `BusinessEvent` subclass in `contract/events.py` (e.g.
  `apps/todo/contract/events.py::TodoCreated`) — a per-app mixin gives `app_name` and the icon,
  the class gives its `verb`; `kind` is derived, never written by hand.
- declared at mount (`AppManifest(emits=[…])`), because `emit` refuses a fact no app owns.
- emitted with the session that carries the mutation, so the fact commits iff the action does.

Only what *happened* is a fact. A refused attempt — a wrong password, a blocked last-owner
change, a non-owner on an owner-only route — changed nothing, so it is a `log.warning`, not a
trail row. It stays visible in the console's Logs screen, on the technical side of the timeline.

To react to another context's flow, subscribe — never call its code.

## Observability (`apps/shared/observability/`)

- **Logging**: `log = structlog.get_logger("labase.<module>.<subject>")`. Emit structured,
  dotted `snake_case` events with kwargs — never f-strings, never `print`:
  `log.info("invitation.sent", email=email, org_id=str(org_id))`.
- **Request tracing**: the `RequestLogger` middleware binds a `request_id` via contextvars —
  nothing to do per feature, but logging structured gets you the correlation for free.
- **Audit**: there is no separate audit call. A sensitive business action (member joined or
  removed, ownership change…) is a `BusinessEvent` emitted on the request's session — see the
  section above — and the console merges the trail with the technical logs into one timeline.

## Cross-cutting surfaces (wire in `contract/integration.py`)

Declare the surfaces decided in the Impact phase as one `AppManifest`, which
`host.register_app` walks in the one correct order — including the trap that the console tile
must register *before* the enabled gate, since a disabled app still shows its tile:

- **Dashboard**: `provides_when_enabled=[(OverviewQuery, _overview)]`. `_overview(query)` reads
  the org-scoped repo (`query.session`, `query.org_id`) and returns an `Overview(key, title,
  icon, href, template, data)` with a Jinja partial `templates/<module>/_overview.html`.
- **Console**: `provides=[(ConsoleOverviewQuery, _console_overview)]` — outside the gate, so the
  tile survives the app being switched off. Aggregates over **all** orgs on the admin session
  (no `org_id`); returns `ConsoleOverview(key, title, icon, data)`.
- **Settings**: `settings=_declare_settings()` returning a `SettingsDeclaration(app_name, defs,
  supabase)`; `register_app` returns the live handle, so `if not settings.enabled: return` works
  immediately. Live reload is wired for you.
- **Menu**: `nav=[NavItem("Todos", "clipboard-text", "todos", "/todos", order=10)]`. For dynamic
  per-org entries, provide `OrgNavQuery` instead (`apps/organizations/contract/fullpage.py`).
- **Facts**: `emits=[TodoCreated, …]` — the events this app owns, so `emit` will accept them.
- **Seeding**: `consumes_when_enabled=[(OrganizationCreated, "<module>_welcome", _seed)]`. The
  handler is `async def _seed(session, event)`: the listener runs it off the trail after the org
  commits, on the admin session, retried and idempotent — never on the creating request's path.
- **Reserved slugs**: `reserve=["<segment>"]` — reserved even when the app is disabled.
- **Feature switch**: `feature_switch()` among the setting defs.

An app whose needs go past this shape (startup hooks, fullpage providers, open lists) keeps an
explicit `mount()` and calls the same primitives directly.

### `mount(host)` for a toggleable app

```python
def mount(host: Host) -> None:
    host.register_app(
        AppManifest(
            settings=_declare_settings(),
            provides=[(ConsoleOverviewQuery, _console_overview)],
            routers=[(router, ORG_PREFIX)],                  # org-scoped: ORG_PREFIX
            nav=[NavItem("Todos", "clipboard-text", "todos", "/todos", order=10)],
            emits=[TodoCreated, TodoDeleted, TodoTicked],
            consumes_when_enabled=[(OrganizationCreated, "todo_welcome", _seed)],
            provides_when_enabled=[(OverviewQuery, _overview)],
        )
    )
```

Source: `apps/todo/contract/integration.py`.

## Templates & HTMX (content negotiation)

Routers serve JSON, an HTMX fragment, or a full page from one handler. Use the helpers in
`apps/shared/http/` — `wants_json(request)`, `wants_full_page(request)` (false for HTMX) — or
the `render_list(...)` helper (`apps/shared/http/responses.py`) passing both `fragment="…
/_x_fragment.html"` and `full=".../x.html"`. Full pages load `fullpage_context`; HTMX
fragments don't — no middleware injects it. Partials are named `_*.html`
(e.g. `_overview.html`, `_list_fragment.html`).

## Styling — daisyUI components (not raw utility soup)

Tailwind CSS 4 + **daisyUI 5**, built via `npm run build:css` into `static/css/tailwind.css`.
daisyUI is the component system — **reuse its components** (`btn` / `btn-primary` /
`btn-sm`, `input`, `card`, `alert` / `alert-error` / `alert-success`, `badge`, `stat`,
`menu`, `link`…) instead of re-spelling long utility chains. Project-specific component
classes live in `@layer components` in `static/css/input.css`: `list-panel` (bordered list
container) and `md-body` (Markdown output wrapper). Add a new shared visual pattern there
(with `@apply`); keep one-off layout (`flex`, `gap-2`, `max-w-2xl`) inline. Icons are
Phosphor (`<i class="ph ph-<name>">`).

## Accessible & semantic HTML

Match the conventions already in `apps/shared/templates/base.html`:

- Use real landmarks and elements: `<nav>`, `<main>`, `<aside>`, `<header>`, `<button>`,
  `<label>` — not `<div>`s with click handlers. Buttons that act are `<button type="...">`;
  navigation is `<a href>`.
- Every form control has a `<label>` (or `aria-label`); required inputs carry `required`.
- Decorative icons are `aria-hidden="true"`; icon-only controls get an `aria-label`
  (e.g. `aria-label="Close navigation"`).
- Keep keyboard focus visible — the component classes already include
  `focus-visible:ring-*`; don't strip outlines.
- `<html lang="en">` is set in the base layout; new pages extend it, so don't re-declare.
- HTMX fragments must remain valid standalone markup (correct heading order, labelled
  controls) since they're swapped into the live DOM.

## Database migrations

Schema changes are versioned SQL under `supabase/migrations/` (Supabase CLI), named
`YYYYMMDD0000NN_<descriptor>.sql`. Enable RLS on each table and **define row access as
policies in the migration** — never re-implement isolation in Python. Add a policy that
references another table only after that table's migration exists (later file).

## Time

Use `clock.now()` (`apps/shared`) as the single source of time — never `datetime.now()`.

## Security — decide per route (not guessable)

- **Authentication**: `CurrentUser` (401 if absent) vs `OptionalCurrentUser` (allows anonymous).
- **Org scoping**: `CurrentOrg` / `CurrentOrgModel` — resolves `{org_handle}`, 403 if not a
  member.
- **Role**: `CurrentMembership` vs `CurrentOwnerMembership` (403 if not owner).
- **Session**: `RlsSession` — Postgres RLS is the source of truth for data isolation; use it
  for user-facing routes. `AdminSession` (BYPASSRLS) only for event handlers, console queries,
  and admin actions.
- RLS is the DB backstop; app-level gates (`require_owner`…) just return a clean 403 first.
- Sources: `apps/auth/contract/current.py`, `apps/organizations/contract/current.py`,
  `apps/shared/persistence/rls.py`.

## Composition

Register a brand-new context in `apps/main.py` (`_apps`, in dependency order; `public` stays
last so its `/{slug}` catch-all doesn't shadow fixed prefixes) and expose its
`mount(host)` from `contract/integration.py`.

## Refactoring

- **Minor** (rename, extract variable, simplify condition): do it immediately.
- **Major** (new abstraction, cross-module restructure): note as TODO, do it later.
