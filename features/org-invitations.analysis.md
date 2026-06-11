# Impact analysis: Organisation invitations

## What this feature covers

Invite a non-member by email with role "member", list pending invitations,
revoke an invitation, accept or decline via a one-time token.  
No email sending in this iteration — the invitation link is returned/displayed.

---

## New entity: `OrgInvitation`

| Column       | Type                           | Notes                                           |
| ------------ | ------------------------------ | ----------------------------------------------- |
| `id`         | `uuid` PK                      |                                                 |
| `org_id`     | `uuid` FK → `organizations.id` | CASCADE DELETE                                  |
| `email`      | `text`                         | invited address                                 |
| `role`       | `org_role`                     | only `member` for now                           |
| `token`      | `uuid`                         | unique, used to accept/decline                  |
| `invited_by` | `uuid`                         | `auth.uid()` at creation                        |
| `status`     | `invitation_status` enum       | `pending` / `accepted` / `declined` / `revoked` |
| `created_at` | `timestamptz`                  |                                                 |

No `expires_at` — revocation is explicit only (by the owner). No "decline" action for the invitee.

---

## RLS & security design

All invitation CRUD (create, list, revoke) runs via **RLS session** (`get_rls_session`).  
The RLS policies enforce owner-only write access; any member can read pending invitations.

**Accepting/declining via token** is the one exception: the invitee may not yet be a member,
so the RLS session cannot resolve `user_is_org_admin` for their token lookup.  
Solution (following `user_is_org_admin` pattern from migration `20260610000001`):
two `SECURITY DEFINER` SQL functions:

```sql
-- Read invitation metadata from token (no membership required)
create function public.get_invitation_by_token(p_token uuid)
returns setof public.org_invitations ...

-- Accept: insert membership + mark accepted atomically
create function public.accept_invitation(p_token uuid)
returns void ...
```

Both functions check `auth.uid()` internally (invitation email must match the authenticated user)
and are the **only** service-role-free paths. The decline path only updates
`org_invitations.status` where `token = p_token AND auth.uid() matches email` — this can be a
targeted `UPDATE` through the RLS session with a permissive policy.

---

## Module changes

### `app/organizations/domain/models.py`

- New `InvitationStatus` enum: `pending`, `accepted`, `revoked`.
- New `OrgInvitation` SQLAlchemy model.
- New DTOs: `InvitationCreate` (email, role), `InvitationRead` (id, org_id, email, role, status, token, created_at).

### `app/organizations/domain/service.py`

New guard: `ensure_not_already_member(repo, org_id, email)` — raises 409 if the email
already has a membership in the org.  
New guard: `ensure_no_pending_invitation(repo, org_id, email)` — raises 409 if a `pending`
invitation already exists for that email.

### `app/organizations/infra/repository.py`

New methods (all via `get_rls_session` except token resolution):

| Method                                               | Session                 | Description                          |
| ---------------------------------------------------- | ----------------------- | ------------------------------------ |
| `create_invitation(org_id, email, role, invited_by)` | RLS                     | INSERT into `org_invitations`        |
| `list_invitations(org_id)`                           | RLS                     | SELECT pending invitations           |
| `get_invitation_by_email(org_id, email, status)`     | RLS                     | check duplicate                      |
| `revoke_invitation(org_id, invitation_id)`           | RLS                     | UPDATE status = revoked              |
| `get_invitation_by_token(token)`                     | SECURITY DEFINER fn     | resolve token (no membership needed) |
| `accept_invitation(token)`                           | SECURITY DEFINER fn     | insert membership + mark accepted    |

### `app/organizations/infra/router.py`

New endpoints:

| Verb     | Path                                       | Action                   | Session             |
| -------- | ------------------------------------------ | ------------------------ | ------------------- |
| `POST`   | `/organizations/{org_id}/invitations`      | Create invitation        | RLS (owner)         |
| `GET`    | `/organizations/{org_id}/invitations`      | List pending             | RLS (member)        |
| `DELETE` | `/organizations/{org_id}/invitations/{id}` | Revoke                   | RLS (owner)         |
| `GET`    | `/invitations/{token}`                     | Show accept/decline page | public              |
| `POST`   | `/invitations/{token}/accept`              | Accept                   | SECURITY DEFINER fn |
The `/invitations/{token}` routes live at root level (not under `/organizations/`) because
the invitee does not know the org_id — they only have the token.

### `app/organizations/tests/steps.py`

New steps:

| Step                                                                                          | Driver method                            |
| --------------------------------------------------------------------------------------------- | ---------------------------------------- |
| `When they invite "{email}" to the organisation with role "{role}"`                           | `invite_member(email, role)`             |
| `When they view the pending invitations list`                                                 | `view_pending_invitations()`             |
| `Then an invitation for "{email}" appears in the pending invitations list with role "{role}"` | `assert_invitation_pending(email, role)` |
| `Then "{email}" does not appear in the pending invitations list`                              | `assert_invitation_absent(email)`        |
| `When they revoke the invitation for "{email}"`                                               | `revoke_invitation(email)`               |
| `When "{email}" accepts the invitation`                                                       | `accept_invitation(email)`               |
| `When "{email}" follows the invitation link again`                                            | `follow_invitation_link_again(email)`    |
| `Then they are redirected to the organisation dashboard`                                      | `assert_redirected_to_org_dashboard()`   |
| `When "{email}" tries to accept the revoked invitation`                                       | `try_accept_revoked_invitation(email)`   |
| `Then the action fails with error "{message}"`                                                | `assert_action_fails_with(message)`      |

Reuses existing `assert_member_with_role` / `assert_member_absent` from `org-members`.

---

## Migration

New file `supabase/migrations/20260612000001_org_invitations.sql`:

- Create `invitation_status` enum.
- Create `org_invitations` table with RLS enabled.
- RLS policies:
  - `SELECT`: any member of the org (via `user_is_org_admin` or membership check).
  - `INSERT`: owner only (`user_is_org_admin`).
  - `UPDATE` (status → revoked): owner only (`user_is_org_admin`).
- `get_invitation_by_token(uuid)` — SECURITY DEFINER.
- `accept_invitation(uuid)` — SECURITY DEFINER (inserts membership + marks accepted, checks email matches `auth.uid()`).

---

## Affected modules summary

| Module                                                   | Change                                                                    |
| -------------------------------------------------------- | ------------------------------------------------------------------------- |
| `app/organizations/domain/models.py`                     | `InvitationStatus`, `OrgInvitation`, `InvitationCreate`, `InvitationRead` |
| `app/organizations/domain/service.py`                    | `ensure_not_already_member`, `ensure_no_pending_invitation`               |
| `app/organizations/infra/repository.py`                  | 7 new methods                                                             |
| `app/organizations/infra/router.py`                      | 6 new endpoints (3 under org, 3 at root)                                  |
| `app/organizations/tests/steps.py`                       | 10 new steps                                                              |
| `app/organizations/tests/driver_mixin_api.py`            | 10 new driver methods                                                     |
| `app/organizations/tests/driver_mixin_browser.py`        | 10 new driver methods                                                     |
| `supabase/migrations/20260612000001_org_invitations.sql` | table + RLS + 2 SECURITY DEFINER functions                                |
