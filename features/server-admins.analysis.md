# Server admin management — integration analysis

Adds the *lifecycle* of the server-admin role that the console already consumes. Today the
role exists only as the `app_metadata.role == "admin"` JWT claim (`auth/infra/security.py`),
set out of band in tests. This feature gives it two real entry points — **bootstrap** (first
registrant) and **designation** (admins managing admins) — mirroring the organisation-owner
dynamic, including a last-admin guard.

## 1. Where the role lives — unchanged storage, new writers

The role stays in GoTrue `app_metadata.role`. No new table. Reading is already done by
`decode_jwt` → `AuthenticatedUser.is_admin`. What's new is **writing** it from app code and
**listing** users with their status. Both go through the Supabase admin API
(`auth.admin.update_user_by_id` / `list_users`), which the test helpers already use.

The claim is materialised in the JWT at sign-in, so a freshly designated user only gains
console access on their next sign-in / token refresh. This is the property the
"after signing in again" scenario asserts; no token surgery is attempted.

## 2. Who owns admin lifecycle — auth owns the claim, console drives the UI

- **auth** owns the GoTrue claim and exposes a thin contract surface to read/write it (it
  already owns user lookup in `auth/contract/admin.py` + `infra/user_repository.py`). Add:
  - `set_server_admin(user_id, is_admin: bool)` — wraps `update_user_by_id` to set/clear
    `app_metadata.role` (clearing = set role to absent/`null`).
  - `list_server_admins()` / `list_all_users_with_admin_flag()` — returns every auth user
    with `email`, `id`, and `is_admin` (read from each user's `app_metadata`). Reuses the
    paginated `list_users` already in `user_repository.py`.
  - `count_server_admins()` — used by both the bootstrap check and the last-admin guard.
- **console** owns the admin-management **surface** (router pages + steps), the same way it
  owns overviews and settings. It calls the auth contract; it never touches GoTrue directly.
  This keeps the "console is the server-owner console" story intact and avoids a second
  context learning the claim shape.

`get_current_admin` (the `404`-hiding gate) is reused verbatim for every new endpoint, so the
"non-admin cannot designate" scenario falls out of the existing denial semantics.

## 3. Bootstrap — first registrant becomes admin

The console subscribes to auth's existing **`UserCreated`** event (already emitted on sign-up
and on email-confirmation). Handler logic: **if `count_server_admins() == 0`, promote this
user.** Counting admins (not total users) is robust to the personal-org seeding that already
runs on `UserCreated` and to leftover non-admin users between tests.

- The handler runs alongside the org context's existing `UserCreated` subscriber. Order does
  not matter — promotion is independent of org creation.
- **The claim is effective at the registrant's first sign-in — no token surgery.** This app's
  `POST /auth/register` deliberately *deletes* the auth cookies and redirects to `/auth/login`
  (router.py): registration never establishes a live session. So the bootstrap promotion (run
  synchronously inside the `UserCreated` emit, before the redirect) is already persisted in
  GoTrue by the time the user signs in, and that first sign-in mints a JWT carrying
  `role=admin`. The bootstrap scenario's "can open the console" therefore holds on the user's
  first real (post-login) session, with no refresh round-trip and no change to `RegisterResult`.
- This is why bootstrap "just works" where designation cannot: a fresh sign-in always re-reads
  the claim, whereas designating an *already-signed-in* other user can't touch their existing
  token — hence the "after signing in again" scenario for that path.
- **Idempotency / races:** two simultaneous first-registrations could both see zero admins.
  Acceptable for this feature (single-operator bootstrap); noted, not guarded.

## 4. Designation & revocation — console endpoints

New routes on the console router, all behind `CurrentAdmin`:

```
GET    /console/admins                  → list every user, is_admin flag      (HTML + JSON)
PUT    /console/admins/{user}           → designate / revoke (set is_admin)   (HTML + JSON)
```

- `{user}` keyed by email (consistent with org-members addressing users by email) resolved via
  `find_user_id_by_email`; designation/revocation = `set_server_admin(uid, True|False)`.
- **Last-admin guard** lives in a console domain function `ensure_not_last_admin(...)`,
  symmetric to organisations' `ensure_not_last_owner`. Revoking when `count_server_admins() == 1`
  and the target is that admin → **403 forbidden** (the `the action is forbidden` step). The
  guard is checked in the domain/service layer, not the router.
- Dual surface per the project convention: browser driver submits the HTMX form and re-renders
  the admin-list fragment; API driver `PUT`s JSON `{is_admin: true|false}`. Same service behind
  both.

## 5. Templates

- `console/templates/console/admins.html` (full page) + `console/_admins.html` (fragment
  re-rendered after a designate/revoke), modelled on the org member-list templates. Each row:
  email, status badge, and a designate/revoke button (disabled for the last admin).
- A link to the admins page is added to the console index (`console.html`) next to the
  overview grid.

## 6. Migrations

None. The role is a GoTrue `app_metadata` claim; no `public.*` table is added or altered.

## 7. Test infra touched

- **New steps** in the console steps module: `the server has no admin yet`,
  `"{email}" is the first registered user`, `"{email}" registers`, `"{email}" has registered`,
  `"{email}" can open the console`, `"{email}" is refused access to the console`,
  `the admin opens the admins page on the console`,
  `"{email}" appears in the admin list as a server admin|a regular user`,
  `the admin designates "{email}" as a server admin`,
  `the admin revokes the server admin rights of "{email}"`,
  `"{email}" signs in again`, `they try to designate "{email}" as a server admin`.
  Reuses `a server admin is signed in as`, `a user is signed in as`,
  `the action is forbidden`, `the console is not found`.
- **New driver methods** on the console api/browser mixins: register a user, open the admins
  page, read a user's row status, designate/revoke, assert console access.
- **`the server has no admin yet`** must clear any lingering `app_metadata.role` in GoTrue so
  the bootstrap count starts at zero — added to the test setup helper (extends
  `auth/tests/given_helpers.py` with a `clear_all_admin_roles()` / per-scenario reset).
- The existing `set_admin_role` helper is reused by the `is a server admin` Given.

## Similarity with organisation owners

The feature is the server-scope twin of org-member management — same *shape*, deliberately
different *mechanism* because an owner is a DB row while a server admin is a JWT claim.

| Concern              | Org owners (`organizations/`)                          | Server admins (this feature)                              |
| -------------------- | ------------------------------------------------------- | ---------------------------------------------------------- |
| Storage              | `memberships` row, `OrgRole` enum, RLS-enforced         | GoTrue `app_metadata.role` claim — no table, no RLS        |
| Authz gate           | `CurrentOwnerMembership` → **403** (acknowledges scope) | `CurrentAdmin` → **404** (hides the console's existence)   |
| List                 | `repo.list_members` + `resolve_user_emails`             | `list_users_with_admin_flag` (one paginated GoTrue scan)   |
| Mutate role          | `PUT /…/members/{email}` role change                    | `PUT /console/admins/{email}` designate/revoke             |
| Last-one guard       | `ensure_not_last_owner` → `count_owners ≤ 1`            | `ensure_not_last_admin` → `count_server_admins == 1`       |
| Guard violation      | `LastOwnerViolation` → 403                               | same → 403 (`the action is forbidden` step)                |
| Counting             | SQL aggregate `count_owners(org_id)`                    | O(users) scan of GoTrue `list_users` (no SQL aggregate)    |

Two divergences worth calling out — both stem from "claim, not row":

1. **Effect timing.** An org role change is read from the DB on the *next request* (via
   `CurrentMembership`/RLS), so it's effectively immediate. A server-admin change lives in the
   JWT, so it only takes effect on the target's next sign-in — hence the explicit "after signing
   in again" scenario, and the bootstrap-only token refresh (§3) to make the first session
   immediate.
2. **Fewer verbs.** Owners have remove / demote / leave (three guarded paths). Server admins
   have only designate / revoke — there's no "membership" to remove and no self-service "leave"
   concept, so the guard has a single trigger (revoke the last admin).

The last-admin guard is intentionally identical in structure to `ensure_not_last_owner`: a
domain function, checked in the service layer, raising a typed violation the router maps to 403.

## Events summary

```
sign-up / email-confirm → emit(UserCreated)
  → organizations: personal org (existing)
  → console:       if count_server_admins() == 0 → set_server_admin(user, True)   ← NEW
  (register then redirects to /auth/login; first sign-in mints a JWT bearing role=admin)

GET /console/admins        → CurrentAdmin → auth.list_users_with_admin_flag()
PUT /console/admins/{email}→ CurrentAdmin → resolve email
                           → revoke? ensure_not_last_admin() → set_server_admin(uid, flag)
                           → re-render admin fragment (HTMX) or JSON
```
