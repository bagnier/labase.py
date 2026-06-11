# Impact analysis: Organisation management

## What this feature covers

Bootstrapping (one org auto-created per user at registration), list, rename, and
dashboard-based navigation between orgs.

### Architectural decisions

- **No cookie-based org switch.** `POST /organizations/switch` and the `active_org_id`
  cookie are removed. They introduce invisible server-side state. All org-scoped routes
  use the org slug from the URL instead.
- **Dashboard as navigation hub.** The dashboard lists all orgs the user belongs to as
  workspace cards. Clicking a card navigates to `/orgs/{slug}/files` (or `/orgs/{slug}/todos`
  etc.). No "active org" concept — the org context is always explicit in the URL.
- **Slug instead of UUID in URLs.** `/orgs/{slug}/...` is readable and shareable.
  The slug is derived from the org name at creation time (lowercased, spaces → hyphens),
  stored as a stable field — renaming the org does not change the slug. Uniqueness enforced
  at DB level.

---

## Current state vs required

| Capability                              | Status                                                  |
| --------------------------------------- | ------------------------------------------------------- |
| Auto-create org at registration         | ✅ exists (`create_with_owner` called in auth router)   |
| List user's orgs (with role)            | ⚠️ exists but role not exposed in DTO                  |
| Rename (owner/admin via RLS)            | ⚠️ exists but uses `get_service_session` + app check   |
| Cookie-based org switch                 | ❌ to be removed                                        |
| Dashboard workspace cards               | ❌ missing                                              |
| Org slug                                | ❌ missing — migration needed                           |
| Org-scoped URLs `/orgs/{slug}/...`      | ❌ missing — all existing routers use `/files`, `/todos`|
| `they are its owner` assertion          | ❌ role not returned by `GET /organizations`            |
| Org isolation (cross-user)              | ✅ RLS policy exists; not asserted in any scenario yet  |

---

## Module changes

### Migration — new `slug` column

```sql
ALTER TABLE organizations ADD COLUMN slug text NOT NULL DEFAULT '';
CREATE UNIQUE INDEX organizations_slug_unique ON organizations (slug);
```

Slug generated in Python at `create_with_owner` time: `re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')`.
Collision handling: append `-2`, `-3`, etc. (repository responsibility).

### `app/organizations/domain/models.py`

- Add `slug: str` to `Organization`.
- Add `OrganizationWithRoleRead(OrganizationRead)` with `role: OrgRole` and `slug: str`.

### `app/organizations/infra/repository.py`

- `create_with_owner`: accept and store `slug`, generate it from `name`.
- New `list_with_role_for_user`: join `memberships`, return `list[tuple[Organization, OrgRole]]`.
- New `get_by_slug(slug) -> Organization | None`.

### `app/organizations/infra/router.py`

- `GET /organizations`: return `list[OrganizationWithRoleRead]` (exposes role + slug).
- `PATCH /organizations/{org_id}` **rename**: migrate from `get_service_session` + app role check
  to `get_rls_session`. RLS policy `"organizations: owner update"` already enforces ownership.
  App-level check removed.
- `POST /organizations/switch`: **deleted**.

### `app/organizations/infra/context.py`

- `get_current_org`: rewrite to resolve from URL path parameter `slug` instead of cookie.
  New signature: `get_current_org(slug: str = Path(...))` returning `uuid.UUID`.
  Still uses `get_service_session` — infrastructure routing, justified.
- `get_current_membership`: unchanged signature, depends on updated `get_current_org`.
- All existing routers (`/files`, `/todos`, `/dashboard`) must be re-prefixed under
  `/orgs/{slug}/` — **this is a breaking change to all existing routes**.
  Scope note: the route refactor is a prerequisite for this feature but touches many files.
  It can be done as a single mechanical rename step before the per-scenario BDD cycle.

### `app/dashboard/`

- Dashboard template gains a workspace card grid: org name, slug, user's role, link to
  `/orgs/{slug}/files`.
- For single-org users: redirect directly to `/orgs/{slug}/files` (no card selection needed).

---

## RLS audit

| Operation      | Session used          | RLS policy                          | Verdict                           |
| -------------- | --------------------- | ----------------------------------- | --------------------------------- |
| List orgs      | `get_rls_session`     | `"organizations: member read"`      | ✅ correct                        |
| Rename org     | `get_service_session` | app check (role in owner/admin)     | ⚠️ migrate to `get_rls_session`  |
| Resolve org    | `get_service_session` | infrastructure routing (slug→id)    | ✅ justified                      |

---

## Test infrastructure

### New steps — `app/organizations/tests/steps.py`

| Step | Driver method |
|------|---------------|
| `Then they have exactly one organisation` | `assert_org_count(1)` |
| `Then they are its owner` | `assert_is_owner()` |
| `When they view their organisation list` | `view_org_list()` |
| `Then "X" appears in their organisation list` | `assert_org_visible(name)` |
| `Then "X" no longer appears in their organisation list` | `assert_org_absent(name)` |
| `When they rename the active organisation to "X"` | `rename_active_org(name)` |
| `Then the action is forbidden` | `assert_action_forbidden()` — 403 |
| `When they view the dashboard` | `view_dashboard()` |
| `Then "X" appears as a workspace card` | `assert_workspace_card(name)` |
| `Given they have also joined "X" as member "email"` | `join_org_as(org_name, email)` |
| `Given they are signed in as "email" in the same org` | `sign_in_same_org(email)` |
| `When "email" views their organisation list` | `view_org_list_as(email)` |
| `Then "email"'s organisation does not appear in the list` | `assert_other_org_absent(email)` |

Steps `"bob@example.com" is a member of the org` and `Then the action is rejected` reused
from `app/files/tests/steps.py`.

---

## Migration needed

| Change | Type |
|--------|------|
| `ALTER TABLE organizations ADD COLUMN slug text` | SQL migration |
| Remove `active_org_id` cookie logic from `context.py` | Python only |
| Re-prefix all routes under `/orgs/{slug}/` | Python only (breaking) |

---

## Affected modules summary

| Module | Change |
|--------|--------|
| `app/organizations/domain/models.py` | Add `slug`; add `OrganizationWithRoleRead` |
| `app/organizations/infra/repository.py` | `create_with_owner` stores slug; `list_with_role_for_user`; `get_by_slug` |
| `app/organizations/infra/router.py` | Rename via RLS; remove switch; expose role+slug in list |
| `app/organizations/infra/context.py` | Replace cookie with slug path param |
| `app/dashboard/` | Workspace card grid; single-org redirect |
| `app/files/infra/router.py` + `app/todo/infra/router.py` | Re-prefix to `/orgs/{slug}/...` |
| `app/organizations/tests/steps.py` | New file |
| `app/organizations/tests/driver_mixin_api.py` | New file |
| `app/organizations/tests/driver_mixin_browser.py` | New file (stubs for multi-user) |
| `app/organizations/tests/test_scenarios.py` | New file |
| `conftest.py` | Register new steps module |
| `tests/e2e/drivers/api.py` / `browser.py` | Compose new mixin |
| `tests/e2e/drivers/protocols.py` | Extend protocol |
| `supabase/migrations/` | Add `slug` column + unique index |
