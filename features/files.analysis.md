# Impact analysis: Org file storage (extended)

## New capabilities vs current state

| Capability                                 | Status                                             |
| ------------------------------------------ | -------------------------------------------------- |
| Upload / List / Download / Delete          | ✅ exists                                           |
| Rename                                     | ❌ missing                                          |
| Ownership-based delete permission          | ❌ missing                                          |
| Admin override on delete                   | ❌ missing                                          |
| File metadata (size, date, uploader email) | ❌ partially (size + date in DB; email not exposed) |
| Org isolation test                         | ❌ untested (RLS not asserted in scenarios)         |
| Share link (public, anyone with link)      | ❌ missing                                          |
| Multi-user test helpers (`bob`, `carol`)   | ❌ missing in drivers/steps                         |

---

## Domain changes

### `OrgFile` model — `app/files/domain/models.py`

- No new columns needed for rename or permissions.
- `OrgFileRead` DTO: add `uploader_email: str` field. The email must be resolved at query time (join or lookup against `auth.users` via service role, or stored at upload time).
  - **Decision**: store `uploader_email: str` on `OrgFile` at upload time — simpler, avoids joins, survives user deletion.

### Ownership check — `app/files/infra/router.py`

Delete and rename endpoints must check: `file.user_id == current_user.id OR current_membership.role in (owner, admin)`.

- `get_current_org` returns only `org_id`; we need the full `Membership` to read the role.
- Add `get_current_membership` dependency (new, in `app/organizations/infra/context.py`) that returns the `Membership` object.

### Rename endpoint

New: `PATCH /files/{file_id}` with body `{"filename": "new-name.pdf"}`.

- Renames only the `filename` field in the DB (display name).
- Does **not** rename the file in Supabase Storage (the `storage_path` stays stable under `{org_id}/{file_id}_{original}`).

### Share link endpoint

New: `POST /files/{file_id}/share` → returns `{"url": "/files/share/{token}"}`.

- Generates a random UUID token, stores it in a new `org_file_share_tokens` table (`token`, `file_id`, `expires_at`).
- TTL: fixed at 7 days; can be made configurable later.
- New public endpoint `GET /files/share/{token}` (no auth required): looks up the token, checks expiry, then redirects to a short-lived Supabase signed URL generated with the **user storage client** (user JWT of the original uploader stored at token creation time — or service role only for this one redirect, explicitly scoped and justified as the app acting on behalf of the share grant).
- **Alternative (preferred, fully tenant-proof)**: the public endpoint streams or proxies the file bytes directly from Supabase Storage using the service role only inside the app boundary — the service role never leaks to the client, and the app enforces the token validity. The share token IS the authorisation gate.
- The driver stores the `/files/share/{token}` URL; `a non-member accesses the share link` hits it directly (no app auth cookie needed).

---

## Storage client

Replace `service_storage_client()` with `user_storage_client(access_token: str)` in `app/files/infra/storage.py`.

All upload, download (signed URL), and delete operations in `app/files/infra/router.py` pass the current user's JWT. Supabase Storage RLS policies on bucket `org-files` enforce that the user belongs to the org (via the existing `user_orgs()` function).

The only legitimate use of the service role in the files context is inside the public share endpoint (see above), where the app acts as the authorisation gate via the share token.

`get_current_org` in `app/organizations/infra/context.py` already uses `get_service_session` to resolve the active org — this is infrastructure-level routing, not tenant data access, and remains unchanged.

---

## Repository changes — `app/files/infra/repository.py`

- `add()`: accept `uploader_email: str`, persist it.
- `get()`: existing, unchanged.
- New `rename()`: update `filename` field.
- New `add_share_token()` / `get_share_token()`: manage `OrgFileShareToken` rows.
- `list_for_org()`: unchanged (SQL); `OrgFileRead` DTO now exposes `uploader_email`.

---

## Migration

```sql
ALTER TABLE org_files ADD COLUMN uploader_email text NOT NULL DEFAULT '';

CREATE TABLE org_file_share_tokens (
    token       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id     uuid NOT NULL REFERENCES org_files(id) ON DELETE CASCADE,
    expires_at  timestamptz NOT NULL
);
```

---

## Test infrastructure

### New auth step — `app/auth/tests/steps.py`

- `Given a user is signed in as "{email}" within org "{org_name}"`: registers `email` with a random password, creates their auto-org, then **renames** that org to `org_name`. Sets the driver's current user to `email`.

### New file steps — `app/files/tests/steps.py`

All new steps call driver methods; no logic in steps.

| Step                                                                               | New driver method                                           |
| ---------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `they upload "x" to the org`                                                       | rename existing `upload_file` (step wording change)         |
| `they upload a file of 51 MB to the org`                                           | `upload_oversized_file(size_mb)`                            |
| `they download "x"`                                                                | rename existing `download_file` (step wording change)       |
| `they delete "x"`                                                                  | rename existing `delete_file` (step wording change)         |
| `they rename "x" to "y"`                                                           | `rename_file(old, new)`                                     |
| `they have generated a share link for "x"`                                         | `generate_share_link(filename)` → stores URL on driver      |
| `"bob" is a member of the org`                                                     | `add_member_to_org(email)` — registers bob, adds membership |
| `"bob" has uploaded "x" to the org`                                                | `upload_file_as(email, filename)`                           |
| `"bob" has uploaded "x" of 9 KB to the org`                                        | `upload_file_as(email, filename, size_kb)`                  |
| `"bob" views the file list`                                                        | `view_file_list_as(email)`                                  |
| `"carol" is a member of "Beta Corp"`                                               | `create_user_in_org(email, org_name)`                       |
| `they are an admin of the org`                                                     | `promote_to_admin(current_user_email)`                      |
| `"bob" accesses the share link`                                                    | `access_share_link_as(email)`                               |
| `a non-member accesses the share link`                                             | `access_share_link_unauthenticated()`                       |
| `the action is denied`                                                             | `assert_action_denied()` → 403                              |
| `the action is rejected`                                                           | `assert_action_rejected()` → 413 or 422                     |
| `"x" still appears in the file list`                                               | `assert_file_visible(filename)` (reuse)                     |
| `"x" does not appear in the file list`                                             | `assert_file_absent(filename)` (reuse)                      |
| `"x" appears in the file list with size "9 KB", uploaded by "bob" on "2026-06-10"` | `assert_file_metadata(filename, size, email, date)`         |

### Driver implementation notes

- `add_member_to_org` / `upload_file_as` / `view_file_list_as`: API driver uses a second `AsyncClient` authenticated as that user; browser driver uses a second browser context.
- `access_share_link_unauthenticated()`: API driver calls the stored URL with a plain `httpx.AsyncClient` (no auth cookies). Browser driver navigates to it in a fresh context.
- `assert_file_metadata`: API driver checks JSON; browser driver reads DOM cells.
- `upload_oversized_file`: generate `size_mb * 1024 * 1024` bytes of zeros in memory. The 50 MB limit is enforced in the upload endpoint (`len(content) > 50 * 1024 * 1024 → 413`). The `Given the org has a file size limit of 50 MB` step is a no-op (the limit is always 50 MB) — it exists for readability only.

---

## Affected modules summary

| Module                                    | Change type                                                                                      |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `app/files/domain/models.py`              | Add `uploader_email` to `OrgFile` + `OrgFileRead`; add `OrgFileShareToken` model                |
| `app/files/infra/storage.py`              | Replace `service_storage_client()` with `user_storage_client(access_token)`                     |
| `app/files/infra/router.py`               | Ownership check (delete/rename); new rename + share + public share endpoints; 50 MB guard        |
| `app/files/infra/repository.py`           | `add()` accepts `uploader_email`; new `rename()`, `add_share_token()`, `get_share_token()` methods |
| `app/organizations/infra/context.py`      | New `get_current_membership` dependency                                                          |
| `app/files/tests/steps.py`                | Many new steps (see table above)                                                                 |
| `app/files/tests/driver_mixin_api.py`     | New methods (see table above)                                                                    |
| `app/files/tests/driver_mixin_browser.py` | Same new methods                                                                                 |
| `app/auth/tests/steps.py`                 | New `within org "{org_name}"` variant of sign-in step                                            |
| `supabase/migrations/`                    | Add `uploader_email` column; create `org_file_share_tokens` table                               |

No changes to: Supabase Storage RLS policies (user JWT already enforces org membership via `user_orgs()`). `get_current_org` keeps `get_service_session` — infrastructure routing, not tenant data.
