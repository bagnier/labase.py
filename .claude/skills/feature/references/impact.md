# Phase 2 — Impact analysis (`features/<name>.analysis.md`)

Identify how the new feature interacts with existing bounded contexts. Produce a short
written summary (a few bullet points, in english), store it in `features/<name>.analysis.md`,
update the scenarios accordingly. **No code yet.** Wait for user validation.

## Integration questions

- Which existing modules, services, or entities does this feature depend on or modify?
- Does it own its data entirely, or share with another context?
- Are there existing endpoints, repositories, or domain models to extend?
- **Coupling**: should this context talk to another through a **domain event**
  (`host.events.emit` / `collect`) or a read-only `contract/queries.py` function — rather
  than a direct import? Cross-app imports go through `contract/` only (see `build.md`).

## Surfaces checklist — design is not just the `.feature` screens

An app usually contributes to cross-cutting surfaces wired through the event bus. Decide,
for each, whether this feature participates (implementation details are in `build.md`):

- **Org dashboard** — does it show a card? → an `OverviewQuery` handler returning an
  `Overview(key, title, icon, href, template, data)`.
- **Admin console** — does it show a server-wide stat? → a `ConsoleOverviewQuery` handler
  returning a `ConsoleOverview(key, title, icon, data)`, aggregated over *all* orgs with the
  admin (BYPASSRLS) session, no `org_id`.
- **Menu** — does it add a sidebar entry? → a `NavItem(label, icon, segment, match, order,
  owner_only)` via `host.register_nav(...)`. Dynamic per-org entries instead → a
  `OrgNavQuery` handler (e.g. pages contributing its published pages).
- **Seeding** — does a new org need starter data? → subscribe to the `OrgCreated` event and
  write with the admin (BYPASSRLS) session. This is how the sign-up chain seeds welcome data
  (`signup → UserCreated → OrgCreated → {files, learning, todo} seed`).
- **Settings** — does it have admin-tunable values? → `declare_app_settings(...)` with
  `SettingDef`s, plus live-reload on `SettingsChanged`.
- **Feature switch** — should the whole app be on/off-able by an admin? → declare a
  `feature_switch()` setting and short-circuit `mount()` when disabled.
- **Reserved slugs** — does it own a fixed URL segment under `/{org_handle}`-space (e.g.
  `files`, `invitations`)? → `host.reserve(...)` so no org handle can shadow it.
- **Security** — for each route, decide: public / member / owner? org-scoped? RLS session or
  admin session? (RLS in `supabase/migrations/` is the single source of truth for isolation.)

## Data & migrations

- Does this feature add or change tables? Schema changes are versioned SQL in
  `supabase/migrations/` (Supabase CLI), **never** ad-hoc in Python.
- Each table enables RLS; **row access is decided by policies in the migration**, not
  re-implemented in app code. Note the policy intent here (e.g. "org members read/write").

Record these decisions in the analysis file. Wait for user validation before Design.
