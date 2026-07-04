# Calendar — Impact analysis

A new **org-scoped bounded context** `apps/calendar/`, modelled on `pages` (org scoping,
reserved slug, dashboard + console overviews, RLS "org members") and `todo` (console overview,
settings, feature switch). It **owns all its data**; no existing table or model changes.

## Ownership & data

- New table `calendar_events` — owned entirely by this context.
- ORM `CalendarEvent`: `id`, `org_id` (FK `organizations`), `user_id` (FK `auth.users`, the
  creator), `title`, `starts_at` (timestamptz), `ends_at` (timestamptz), `location` (text,
  default `''`), `description` (text, default `''`), `created_at`, `updated_at`, `version`
  (optimistic lock, like `Page`).
- DTO `CalendarEventRead` for JSON responses (Pydantic, `from_attributes`).
- Repository `CalendarEventRepository(OrgScopedRepository[CalendarEvent])` + a module-level
  `count_all(session)` for the server-wide console count (mirrors `pages.count_all`).

## Coupling — all cross-context access via `contract/`, no direct imports

This context **emits no new events** in v1; it only **consumes** existing contract surfaces:

- `apps.organizations.contract` — `ORG_PREFIX`, `CurrentOrg`, `CurrentMembership`,
  `CurrentOrgModel`, and `Overview`/`OverviewQuery`. **No owner gate** — any member writes,
  so `CurrentMembership` (membership = read+write), never `CurrentOwnerMembership`.
- `apps.settings.contract` — `ConsoleOverview`/`ConsoleOverviewQuery`, `declare_app_settings`,
  `SettingDef`, `feature_switch`, `SupabaseLink`, `SettingsChanged`, `get_app_settings`.
- `apps.auth.contract.current` — `CurrentUser`, `RlsSession`.
- `apps.profile.contract.fullpage` — `fullpage_context` (full HTML pages).
- `apps.shared` — `clock` (single time source; **never** `datetime.now()`),
  `OrgScopedRepository`, `AdminSession` (BYPASSRLS, console count only), `templates`,
  `record_audit_event`, `wants_json` / `parse_body` / `or_404`.

## Surfaces checklist

- **Org dashboard (`OverviewQuery`)** — YES. `_overview` returns an `Overview(key="calendar",
  title="Calendar", icon="calendar-dots", href="calendar", template="calendar/_overview.html")`.
  `data.lines` = `["N upcoming"]` or `["No upcoming events"]`; `data.recent` = titles of the
  next few upcoming events. **"Upcoming" = `starts_at >= clock.now()`**, ordered ascending.
- **Admin console (`ConsoleOverviewQuery`)** — YES. `_console_overview` uses `count_all` over
  the BYPASSRLS admin session → `["N events"]` (every event, all orgs, past + future). Console
  presence registered **even when the app is disabled**, so an admin can re-enable it.
- **Menu (`NavItem`)** — YES. `host.register_nav(NavItem("Calendar", "calendar-dots",
  "calendar", "/calendar", order=20))` (between Todos=10 and Pages=25). Not `owner_only`.
  No `ShellOrgQuery` (no dynamic per-org sub-entries like pages' published pages).
- **Seeding (`OrgCreated`)** — **YES, a single welcome event dated today.** On `OrgCreated`,
  `_seed` writes one event (e.g. "Welcome to your team calendar", today 09:00–09:30 via
  `clock.now()`) with the admin (BYPASSRLS) session, `user_id` = org owner (`get_org_owner_id`),
  mirroring `todo._seed`. **This does not affect any scenario**: `OrgCreated` is emitted only
  when `db_schema != "test"` (see `organizations/contract/integration.py` —
  `if event.access_token and get_technical_settings().db_schema != "test"`), so seeding never
  runs under the E2E drivers, exactly like todo/files/learning. The welcome event is a
  production-only behaviour with no BDD coverage (matching the existing seed handlers, which
  have no tests). Empty-calendar and dashboard empty-state scenarios therefore stay valid.
- **Settings (`declare_app_settings`)** — YES, minimal: `feature_switch()` only, plus a
  `SupabaseLink("Browse events in Supabase", table="calendar_events")`. No tunables in v1.
  Subscribe to `SettingsChanged` to live-reload if any value is added later.
- **Feature switch** — YES, via `feature_switch()`; `mount()` short-circuits when disabled but
  still answers `ConsoleOverviewQuery` and still `reserve("calendar")` (mirrors pages/todo).
- **Reserved slugs** — YES. `host.reserve("calendar")` (kept even when disabled, so no org
  handle squats it). Mounted under `ORG_PREFIX` after fixed-prefix routers (see `apps.main`).

## Security (RLS is the single source of isolation)

- **All routes member-only & org-scoped**, under `/{org_handle}/calendar`, using `RlsSession`;
  `CurrentMembership` enforces the caller belongs to the org. Cross-org reads return nothing
  (covered by the "different org cannot see the events" scenario) — enforced by RLS, not Python.
- **No public / anon routes** (members-only v1): no root-mounted public router, no `anon` grant.
- **No owner-only routes** (any member creates/edits/deletes).
- **Validation in both layers** (decision: both). The router returns HTTP 422 → the
  `event is rejected` outcome (empty title; `ends_at` must be after `starts_at`), **and** the
  table carries a `check (ends_at > starts_at)` constraint as defence-in-depth.

## Data & migration

- New migration `supabase/migrations/20260626000001_calendar_events.sql`:
  - `create table public.calendar_events (...)` with FKs `org_id → organizations(id)` and
    `user_id → auth.users(id)`, both `on delete cascade`; `check (ends_at > starts_at)`.
  - `create trigger calendar_events_updated_at ... execute procedure public.set_updated_at();`
  - `create index calendar_events_org on public.calendar_events (org_id, starts_at);`
  - `alter table ... enable row level security;`
  - Policy **`"calendar_events: org members"` `for all`** —
    `using (org_id in (select public.user_orgs())) with check (org_id in (select public.user_orgs()))`.
    No anon `select` policy (members-only).
  - `grant select, insert, update, delete on public.calendar_events to authenticated;`
    (no grant to `anon`).

## Display formatting (cross-driver contract)

The "shows the time" assertions (`"1 July 2026, 14:00 – 15:00"`) must be identical under both
drivers. A single domain helper `format_event_time(starts_at, ends_at)` produces the string;
the HTML detail view renders it **and** `CalendarEventRead` exposes it as a `when` field, so the
browser driver reads it from the page and the API driver reads it from JSON — same literal.

## Scenarios impact

No scenario changes required. The two semantics that the scenarios pin are confirmed by this
design: dashboard `"1 upcoming"` (Kickoff future / Retro past, by `starts_at`) and console
`"2 events"` (total rows across Acme + Globex). The "empty calendar" / dashboard empty-state
scenarios stay honest because `OrgCreated` (hence welcome-event seeding) is suppressed in the
test schema — the same reason todo/files/learning seeds don't perturb their count assertions.
