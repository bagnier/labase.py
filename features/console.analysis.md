# Console — integration analysis

The console is a **server-wide, admin-only** context with two surfaces: global overviews
(read) and per-app settings (read + write). It mirrors the org-dashboard overview pattern
(`OverviewQuery` collected over the event bus) but adds a *write* path and a *server-wide*
(all-organisations) scope.

## 1. Admin role — the Supabase-idiomatic way

There is no admin notion today. We use the Supabase-idiomatic admin-controlled claim:

- **`app_metadata.role`**: GoTrue embeds `app_metadata` in every access token automatically, and
  it is writable only via the admin API (never by the user). Setting
  `app_metadata = {"role": "admin"}` on a user marks a server admin — no migration, no Custom
  Access Token Hook, no Supabase restart. (The hook + `user_roles` table is the heavier RBAC
  variant; its only extra power is exposing the role to RLS — unused here, since the console
  reads/writes through the BYPASSRLS admin session, gated at the HTTP layer.)
- **`auth/infra/security.py`**: `decode_jwt` payload already read; set
  `AuthenticatedUser.is_admin = payload.get("app_metadata", {}).get("role") == "admin"`.
- **`auth/contract/user.py`**: add `is_admin: bool = False` to `AuthenticatedUser`.
- **`auth/contract/current.py`**: add a new dependency `CurrentAdmin` that returns the user if
  admin. It is the single gate the console router depends on — symmetric to
  `CurrentOwnerMembership`. **Denial semantics hide the console's existence:**
  - anonymous (no/invalid token) → `401` (standard auth, redirect to sign-in), unchanged;
  - signed-in **non-admin** → `404 Not found` (a `403` would confirm the console exists).

  So `CurrentAdmin` raises `404` for an authenticated non-admin and lets the auth layer raise
  `401` for anonymous. The "access is denied" Gherkin step asserts: 401 for the anonymous
  scenario, 404 for the non-admin scenarios.

Consequence: the claim is materialised at sign-in. Tests promote a user to admin *before* they
sign in (new GoTrue/DB helper), so the issued token carries the claim.

## 2. Global overviews (read) — server-wide collect

Symmetric to `OverviewQuery` but without `org_id` and aggregating across every org:

- **`console/contract/overviews.py`** (owned by console, the asker): `ConsoleOverview`
  dataclass (`key`, `title`, `icon`, `data` with `lines`) and `ConsoleOverviewQuery(session)`.
- Each app answers in its `contract/integration.py` via `host.events.on(ConsoleOverviewQuery, …)`,
  reusing its repository but counting **all rows** (no org filter). The console passes a
  **BYPASSRLS admin session** so the aggregate sees every organisation.
- **`console/infra/router.py`** collects them: `host.events.collect(ConsoleOverviewQuery(session))`
  — a failing provider is isolated, not fatal (same guarantee as the dashboard).
- The console needs the `Host` at request time; the router will close over `host` the same way
  `organizations/infra/router.py` does.

## 3. Settings (read + write) — declared by apps, stored by console

Same "publish via the bus" idea as overviews, but bidirectional: apps **declare** their settings
(keys, types, defaults); the console **persists overrides** and serves the effective value.

- **`console/contract/settings.py`**: `SettingDef(key, type: "string"|"number"|"boolean",
  default, label)` and `SettingsGroup(app, defs)`; query event `ConsoleSettingsQuery()`.
- Each app answers `ConsoleSettingsQuery` in its `contract/integration.py` with its
  `SettingsGroup`. The `files` app declares: `max_upload_mb` (number, 25),
  `uploads_enabled` (boolean, true), `welcome_message` (string, "Welcome aboard").
- **`public.app_settings`** table (`app text`, `key text`, `value text`, primary key `(app, key)`)
  — new migration, BYPASSRLS-only writes. Stores **overrides** only; unset keys fall back to the
  declared default. `value` stored as text, coerced by the declared `type`.
- **`console/domain/`** (`models.py`, `service.py`) merges declared defaults with persisted
  overrides → effective settings; validates the written value against the declared type.
  **`console/infra/repository.py`** is the only writer of `app_settings`, via the admin session.
- App-side consumption (apps reading their effective settings to *act* on them, e.g. files
  enforcing `uploads_enabled`) is a **future contract surface** (`console/contract` read helper);
  out of scope for these scenarios, which only assert the console read-after-write round-trip.

## Dual surface — JSON & web (both read and write)

Settings are editable over **both** an HTML form (web) and a JSON API, per the project's
`wants_json(request)` convention (every router serves both). Concretely:

- **Read** `GET /console` (and `/console/settings`): HTML page/fragment for the browser, JSON
  body (the merged effective settings, grouped by app, each value typed) for API clients.
- **Write** `PUT /console/{app}/settings/{key}`: idempotent set of one setting's value. Accepts
  an HTML form submit (HTMX `hx-put`, re-renders the settings fragment) **and** a JSON body
  `{value}` (returns the updated effective settings as JSON). Same domain service + validation
  behind both; the router only differs in parse/serialize.

This is why scenarios run green under **both** drivers: the `BrowserDriver` fills/submits the
form, the `ApiDriver` PUTs/POSTs JSON to the same endpoint.

## Data ownership & boundaries

- Console **owns** `user_roles`? No — `user_roles` is auth-adjacent; it lives in the auth
  migration set and is read by `decode_jwt`. Console owns only `app_settings` and the two query
  events. Apps depend on `console/contract` to declare settings/overviews (allowed: contract is
  the sanctioned public surface), and console never imports app internals.
- No new RLS-enforced read path for app code here: aggregation and settings writes go through the
  **BYPASSRLS admin session** (`get_admin_session` / `admin_session_factory`), justified because
  the console is explicitly cross-tenant and admin-gated at the HTTP layer by `CurrentAdmin`.

## Events summary

The console is a **drill-down**: the home page is the overview grid; each overview card links to
that app's detail page, which recaps its metrics and exposes its settings. Settings are reached
*through* an app's overview — overview and settings share one per-app entry point.

```
GET  /console               → CurrentAdmin gate
                            → collect(ConsoleOverviewQuery(admin_session))  ← files/learning/todo
                            → also count each app's declared settings (ConsoleSettingsQuery)
                            → overview grid, each card links to /console/{app}
GET  /console/{app}         → CurrentAdmin gate
                            → renders the SAME overview partial as the grid (reused, not
                              rebuilt) + merged settings (defaults ⊕ app_settings)
PUT /console/{app}/settings/{key}
                            → CurrentAdmin gate → validate against SettingDef → upsert app_settings
                            → re-render the settings fragment (HTMX) or JSON (wants_json)
```

## Test infra touched

- `app/auth/tests/given_helpers.py`: `promote_to_admin(email)` (write `user_roles`) before sign-in.
- New console steps + driver mixins (api/browser); register in `conftest.py` and the drivers.
- Reuses existing auth sign-in steps and the files upload `Given` from the dashboard feature.
</content>
