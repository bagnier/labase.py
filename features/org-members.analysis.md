# Impact analysis: Organisation member management

## What this feature covers

List members (with roles), change a member's role, remove a member, leave an
organisation — all guarded by the invariant that at least one owner must remain.

---

## Current state vs required

| Capability                                  | Status                                              |
| ------------------------------------------- | --------------------------------------------------- |
| List members of an org                      | ❌ no endpoint                                      |
| Change a member's role                      | ❌ no endpoint                                      |
| Remove a member                             | ❌ no endpoint                                      |
| Leave an org                                | ❌ no endpoint                                      |
| Last-owner guard (remove / demote / leave)  | ❌ no logic                                         |
| `GET /organizations` exposes role           | ✅ already (`OrganizationWithRoleRead`)             |
| RLS: owner can insert/update/delete members | ✅ `user_is_org_owner` (migration 20260611000001)   |
| `sign_in_within_org` step (Background)      | ⚠️ new variant needed: `as owner of "{org_name}"`  |

---

## Module changes

### `app/organizations/domain/models.py`

- Add `MemberRead` DTO: `auth_user_id`, `email` (resolved at router layer), `role`, `created_at`.
- No new domain entities — `Membership` is sufficient.

### `app/organizations/domain/service.py` (new file)

Single responsibility: enforce the last-owner invariant.

```python
async def ensure_not_last_owner(repo, org_id, target_user_id) -> None:
    """Raise HTTP 403 if removing/demoting target_user_id would leave the org ownerless."""
```

Called by router before any membership delete or role-downgrade.

### `app/organizations/infra/repository.py`

New methods (all via `get_rls_session` — RLS enforces owner-only access):

| Method | Description |
|--------|-------------|
| `list_members(org_id)` | `SELECT * FROM memberships WHERE org_id = ?` |
| `count_owners(org_id)` | `SELECT count(*) WHERE org_id = ? AND role = 'owner'` |
| `update_member_role(org_id, user_id, role)` | `UPDATE memberships SET role = ?` |
| `remove_member(org_id, user_id)` | `DELETE FROM memberships WHERE ...` |

All operate on `get_rls_session`: RLS policies (`memberships: owner insert/update/delete`)
block non-owners at the database level. The service layer adds the last-owner guard on top.

### `app/organizations/infra/router.py`

New endpoints under `/organizations/{org_id}/members`:

| Verb | Path | Action | Auth |
|------|------|--------|------|
| `GET` | `/organizations/{org_id}/members` | List members | any member (RLS read) |
| `PATCH` | `/organizations/{org_id}/members/{user_id}` | Change role | owner (RLS update) |
| `DELETE` | `/organizations/{org_id}/members/{user_id}` | Remove member | owner (RLS delete) |
| `DELETE` | `/organizations/{org_id}/members/me` | Leave org | any member |

Response for member endpoints: `MemberRead` (or list thereof).
`email` field: resolved by a single `auth.admin.getUserById` call at the router layer
(service-role call, justified: auth.users is not accessible via RLS).

Last-owner guard applied at router level (before DB write) for PATCH and DELETE.

### `app/auth/tests/steps.py`

New step: `a user is signed in as "{email}" as owner of "{org_name}"`.  
Creates a fresh org named `org_name` with `email` as owner (via `create_with_owner`),
then signs in. Distinct from `within org` which reuses an existing org.

### `app/organizations/tests/steps.py`

New steps:

| Step | Driver method |
|------|---------------|
| `When they view the member list` | `view_member_list()` |
| `Then "{email}" appears in the member list with role "{role}"` | `assert_member_with_role(email, role)` |
| `Then "{email}" does not appear in the member list` | `assert_member_absent(email)` |
| `When they set the role of "{email}" to "{role}"` | `set_member_role(email, role)` |
| `When they remove "{email}" from the org` | `remove_member(email)` |
| `When they leave the organisation` | `leave_org()` |
| `Given "{email}" is a member of "{org_name}"` | reuse existing `join_org_as_member` or new `add_member_to_org_named` |

### `app/organizations/tests/driver_mixin_api.py`

New driver methods for all steps above. Use `GET /organizations/{org_id}/members` etc.
`org_id` resolved from the stored `_active_org_slug` via `GET /organizations`.

---

## RLS audit

| Operation | Session | Policy | Verdict |
|-----------|---------|--------|---------|
| List members | `get_rls_session` | `memberships: member read` | ✅ |
| Change role | `get_rls_session` | `memberships: owner update` | ✅ |
| Remove member | `get_rls_session` | `memberships: owner delete` | ✅ |
| Leave (self-delete) | `get_rls_session` | member deletes own row — **not covered** | ⚠️ see below |
| Resolve email for MemberRead | `get_service_session` | auth.users lookup | ✅ justified |

**Leave (self-delete) gap**: the current `memberships: owner delete` policy requires
`user_is_org_owner`. A plain member cannot delete their own row.  
Fix: add a separate policy `memberships: self leave` — `using (auth_user_id = auth.uid())`.
This covers "leave", while the last-owner guard stays at the application layer.

---

## Migration

New file `supabase/migrations/20260611000002_members_self_leave.sql`:

```sql
create policy "memberships: self leave"
  on public.memberships for delete
  using (auth_user_id = auth.uid());
```

No new tables or columns needed.

---

## Affected modules summary

| Module | Change |
|--------|--------|
| `app/organizations/domain/models.py` | Add `MemberRead` DTO |
| `app/organizations/domain/service.py` | New — last-owner guard |
| `app/organizations/infra/repository.py` | `list_members`, `count_owners`, `update_member_role`, `remove_member` |
| `app/organizations/infra/router.py` | 4 new endpoints under `/{org_id}/members` |
| `app/auth/tests/steps.py` | New step `as owner of "{org_name}"` |
| `app/organizations/tests/steps.py` | 6 new steps |
| `app/organizations/tests/driver_mixin_api.py` | 6 new driver methods |
| `supabase/migrations/20260611000002_members_self_leave.sql` | `memberships: self leave` policy |
