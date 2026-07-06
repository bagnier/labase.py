# Profile avatar (+ handle switch) — impact analysis

Two last small advanced-auth options, both in the *profile* context, both
admin-switchable (`profile.avatar_enabled`, `profile.handle_enabled` — the
2026-07-06 decision applied to the whole lot).

## Avatar

- **Storage**: same Supabase Storage bucket as org files, under a reserved
  `avatars/{auth_user_id}` prefix — no new bucket to provision, overwrite on
  re-upload. Uploaded through the service-role storage client; the path is
  forced from the session, so no storage-policy work is needed.
- **Serving**: `GET /profile/avatar/{auth_user_id}` streams from storage
  (signed-in users only — avatars appear next to other members), with cache
  headers. No public bucket, no signed URLs to expire.
- **Model**: `profiles.avatar_path` column (migration) — presence drives the
  `<img>` vs initial-letter fallback on the profile page.
- **Validation**: content-type must be image/png|jpeg|webp, size ≤ 2 MB.
  Audited `profile.avatar_updated`.
- **Switch off**: form hidden, POST/GET answer 404.

## Handle switch

- The behaviour exists (profile.feature covers it); the option only gains its
  declared setting: when `handle_enabled` is false the handle form is hidden
  and handle updates through `POST /profile` are refused (404-equivalent).
- Auto-handle assignment is also skipped when off — a product without public
  identities should not mint them silently.

## Surfaces

- No events, no dashboard/console changes, no new context. One migration
  (profiles.avatar_path). Tests reuse the storage-backed files substrate
  patterns for multipart upload on both drivers.
