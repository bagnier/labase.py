# Production deployment

The road from `make dev` to a hardened, deployed instance. This covers the P0
production-readiness items from [ROADMAP.md](../ROADMAP.md); the P1/P2 items
(CI/CD, alerting, log shipping, runbooks) are tracked there.

Already built into the app, so not repeated here: 4-layer observability, `health/`
liveness/readiness probes, cross-instance rate limiting, RLS, security headers
(HSTS/CSP/X-Frame/nosniff), `Sec-Fetch-Site` CSRF. See [README.md](../README.md).

## Topology

```
client ──HTTPS──▶ Caddy (TLS termination, Let's Encrypt) ──HTTP──▶ app (Hypercorn) ──▶ Supabase
```

`docker/docker-compose.prod.yml` runs two services: `app` (built from
`docker/Dockerfile`) and `caddy` (`docker/Caddyfile`). Postgres, Auth and Storage
are Supabase-managed — not in this compose.

## Deploy

```bash
ENV_FILE=../.env.production \
DOMAIN=app.example.com \
ACME_EMAIL=ops@example.com \
APP_VERSION=$(git rev-parse --short HEAD) \
  docker compose -f docker/docker-compose.prod.yml up -d --build
```

Caddy obtains and renews a TLS certificate for `DOMAIN` automatically. Set an
A/AAAA record to the host first, and open ports 80 and 443. `APP_VERSION` (the git
SHA) drives error-tracking regression detection — always pass it.

## Secrets

`.env` is **not** committed (only `.env.test`, which holds local Supabase demo
keys). Production secrets live in an uncommitted `.env.production` (or your
platform's secret store) and are passed via `env_file` / `ENV_FILE`. Never bake
them into the image.

Minimum production env:

| Variable                                           | Note                                                                  |
| -------------------------------------------------- | --------------------------------------------------------------------- |
| `ENVIRONMENT`                                      | `production` — set by the compose file; activates the preflight gate  |
| `SUPABASE_API_URL`                                 | project API URL                                                       |
| `SUPABASE_PUBLISHABLE_KEY` / `SUPABASE_SECRET_KEY` | project keys; keep the secret key server-side only                    |
| `SUPABASE_DATABASE_USER_URL`                       | **via the Supavisor pooler** (see below), asyncpg driver              |
| `SUPABASE_DATABASE_ADMIN_URL`                      | admin (BYPASSRLS) connection, also pooled                             |
| `COOKIES_SECURE`                                   | `true` (the default) — required over HTTPS                            |
| `CORS_ORIGINS`                                     | explicit origins, **not** `*`                                         |
| `TRUST_FORWARDED_FOR`                              | `true` — required behind Caddy, see [Behind a proxy](#behind-a-proxy) |
| `SMTP_*`                                           | a real transactional provider (not the local Mailpit catcher)         |
| `FIREHOSE_DIR`                                     | fallback log path, used only when Postgres refuses a batch            |
| `LOG_DEBUG`                                        | leave unset: `true` renders logs as console text instead of JSON      |

## Preflight — config safety gate

`make preflight` refuses an unsafe production config. Run it against the prod env
before deploying:

```bash
make preflight ENV_FILE=.env.production
```

Blocking errors: `COOKIES_SECURE=false`, `CORS_ORIGINS` containing `*`, either the user
or the admin database URL pointing at a local host, an unset/too-short secret key.
Warnings: a non-production `ENVIRONMENT`, `APP_VERSION=dev`, `LOG_DEBUG=true` (logs would
render as human-readable console text rather than the JSON an aggregator parses — it no
longer selects a level, since nothing is written below `INFO`), missing admin URL.

The same checks run **at boot** when `ENVIRONMENT=production`
(`apps/shared/preflight.py::enforce_at_boot`): a blocking error raises and the
process refuses to start rather than serving traffic with dev defaults.

## Connection pooling (Supavisor)

asyncpg opens direct Postgres connections; under load, many app instances exhaust
Supabase's connection limit. Route the database URLs through **Supavisor** (Supabase's
pooler) in **transaction mode**, and keep the asyncpg pool per instance small:

- Use the pooler host/port from the Supabase dashboard for both
  `SUPABASE_DATABASE_USER_URL` and `SUPABASE_DATABASE_ADMIN_URL`.
- Transaction-mode pooling disallows session-level features (e.g. some prepared
  statements) — asyncpg's statement cache may need disabling in the URL/driver args.
- Size the per-instance pool against `pooler_connections / instances`.

## Database migrations in production

Migrations are forward-only SQL under `supabase/migrations/`.

- Deploy migrations **from the pipeline**, not by hand: `supabase db push` (`make migrate`)
  against the linked remote project, gated behind `make ci`.
- Practise zero-downtime discipline: no destructive change (`DROP COLUMN`, adding a
  `NOT NULL` without default, renaming) on a live table in the same deploy that ships
  code depending on the new shape — split into expand → migrate data → contract.
- RLS policies are part of the migration; never re-implement isolation in Python.

## Graceful shutdown

On `SIGTERM`, Hypercorn drains in-flight requests before exiting
(`--graceful-timeout`, default 25s in `docker/entrypoint.sh`; `stop_grace_period: 30s`
in the compose file gives the container a little more). The task worker cancels
cleanly on shutdown (`TaskWorker.stop`), releasing its `FOR UPDATE SKIP LOCKED`
claims. `exec` in the entrypoint makes Hypercorn PID 1 so the signal reaches it
directly.

## Backups

Postgres (schema + rows) is covered by the Supabase platform with PITR — see
[docs/backups.md](backups.md). **Storage bytes are not in any SQL dump**, so back
them up separately:

```bash
make backup-storage DEST=/backups/storage ENV_FILE=.env.production
```

This mirrors the whole bucket to `DEST/<bucket>/…`, recursing into folders. Schedule
it (cron / a scheduled job) and verify a restore periodically.

## Behind a proxy

The app reads `COOKIES_SECURE` from config (not the request scheme), so TLS
termination at Caddy needs no scheme detection for auth.

Client IP is the part that does need a setting. Rate limiting keys on the caller's
address (`apps/shared/http/limiter.py`), and behind a proxy the socket peer is Caddy —
so every request would share one bucket, letting a single abuser exhaust the limit for
everyone. Set `TRUST_FORWARDED_FOR=true`: `client_ip` then reads the left-most
`X-Forwarded-For` entry, the client Caddy observed, instead of the peer
(`apps/shared/http/addressing.py`).

It is off by default on purpose — trusting that header when nothing upstream strips it
lets any caller spoof their IP. Turn it on **only** because Caddy sets it and nothing
reaches the app except through Caddy. If you expose the app port directly (no proxy),
leave it off.
