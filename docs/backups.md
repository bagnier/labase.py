# Backups & point-in-time recovery

What is backed up, by whom, and how to get data back. This closes the monitoring
TODO's "backup/PITR doc" half (see [ROADMAP.md](../ROADMAP.md)); metrics and error
tracking are the `apps/metrics` and `apps/issues` bricks.

## What actually needs saving

| Data | Lives in | Covered by a Postgres backup? |
| --- | --- | --- |
| App tables (orgs, todos, pages, …) | Postgres `public` schema | yes |
| Auth users, identities, MFA factors | Postgres `auth` schema (GoTrue) | yes |
| Uploaded files (org files, avatars) | Supabase **Storage** — metadata in Postgres (`storage.objects`), **bytes in object storage** | metadata only — the bytes are NOT in any SQL dump |
| App settings, business events, task queue, metrics, issues | Postgres `public` schema | yes |
| Secrets (`.env`, SMTP, service keys) | env files / your secret store | no — keep them in your secret manager, they are not data |

The one trap: **Storage bytes are outside Postgres**. A database-only restore
brings back every `storage.objects` row but none of the files those rows point
to. Any backup story must pair the DB backup with an object-storage copy.

## Hosted Supabase (production)

Buy, don't build — this is the platform half of the Supabase bet:

- **Daily backups** are automatic on every paid project (retention grows with
  the plan). Restore from Dashboard → Database → Backups.
- **PITR** (Pro add-on) replaces daily snapshots with WAL archiving: restore to
  any second within the retention window (RPO in seconds, not hours). Enable it
  in Dashboard → Database → Backups → Point in Time. Turn it on **before** you
  need it — it only covers time after activation.
- **Storage** is replicated by the platform, but platform durability is not a
  user-error backup: deleting a bucket is deleted. For real protection, mirror
  the bucket externally (the S3-compatible endpoint makes `rclone sync` work)
  on a schedule you own.
- **Logical exports** for cold copies you control:
  `supabase db dump --linked -f backup.sql` (schema + data, run it from cron in
  any environment that holds the project ref + a database password).

Restore drill (do it once per project, before launch): create a scratch
project, restore yesterday's backup into it, point a local `.env` at it, run
the app, open the org dashboard. If that works, your backups are real.

## Local development

Local data is disposable by design (`make db-reset` rebuilds from
`supabase/migrations/`). When you do want a snapshot — e.g. before a risky
migration:

```bash
supabase db dump --local -f /tmp/before.sql --data-only   # data snapshot
make db-reset                                              # replay migrations
psql postgresql://postgres:postgres@localhost:54322/postgres -f /tmp/before.sql
```

Migrations remain the source of truth for **structure**; dumps are only for
**data** you care about between resets.

## Self-hosted / any plain Postgres

If a product outgrows hosted Supabase, the story is standard Postgres:

- `pg_dump` nightly (logical, easy restore of one table) **plus** WAL archiving
  via `pgbackrest` or `wal-g` if you need PITR.
- Mirror the Storage bucket (S3-compatible) with `rclone sync` on the same
  schedule.
- Test restores on a schedule, not after an incident.

## What a product clone should decide at launch

1. PITR on or daily backups enough? (Decide from acceptable data loss, not price.)
2. Where does the external Storage mirror live, and how often does it sync?
3. Who has run the restore drill, and when was it last run?

Write the three answers into the product's own README; the base cannot answer
them for you.
