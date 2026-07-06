# Load metrics — impact analysis

Two layers, one collector (ROADMAP "load metrics" brick). Split of ownership:

- **`apps/shared/observability/metrics.py`** — the in-memory `MetricsAccumulator`:
  cumulative counters per (method, route template, status class) + fixed-boundary
  latency histogram buckets. Fed by `RequestLogger` (already on the path; route
  template read from `request.scope["route"]` after `call_next`, `"unmatched"`
  otherwise). Shared owns *collection only* — it cannot gate routes (shared must
  not import auth).
- **`apps/metrics/`** — new bounded context owning everything with a surface:
  - `GET /metrics` — Prometheus text exposition reading the accumulator live
    (cumulative counters, standard names `http_requests_total`,
    `http_request_duration_seconds_bucket`). Server-admin only, 404 to others
    (same gate as the console).
  - `MetricsFlusher` — per-process lifespan task (like `SettingsRefresher`):
    every `metrics_flush_seconds` (technical setting, default 60, 0 disables —
    tests disable) diffs the accumulator against the previous snapshot and
    writes **deltas**, one row per (instance, minute, method, route). Prometheus
    needs cumulative, flush needs deltas — the flusher keeps the last snapshot.
  - **console "Load" screen** `GET /console/load` — per-route traffic over the
    last 24h: requests, error rate, p95 (computed from the histogram buckets in
    SQL/Python, Prometheus-style). Link-outs to Supabase Studio for the DB side
    (build, don't rebuild pg stats).
  - **retention** — daily `metrics.rollup` recurring task on the async substrate:
    minute rows older than 7 days downsampled to hour buckets, hour rows older
    than `retention_days` purged.

## Surfaces

- **Console overview**: `ConsoleOverview(key="metrics")` showing requests over 24h
  → scenario "console overview sums the recent traffic".
- **Org dashboard**: none — server-level data, not org data.
- **Menu / seeding / org nav**: none.
- **Settings** (`declare_app_settings`): `feature_switch` (whole app off),
  `retention_days` (default 30, hour-bucket purge). Flush interval and minute
  retention stay technical (env), not admin-tunable.
- **Reserved slugs**: `host.reserve("metrics")` and `host.reserve("load")` is not
  needed (`/console/load` is not in org space); `/metrics` is root-level so it is
  reserved against org handles.
- **Security**: `/metrics` and `/console/load` = server admin only (404 otherwise);
  writes happen on the admin session (server-level data, like `error_groups`).

## Data & migrations

- `request_metrics` table (new migration): `bucket timestamptz` (minute),
  `instance text`, `method text`, `route text`, `resolution text` (minute|hour),
  `requests int`, `errors int`, `duration_buckets int[]` (aligned with the fixed
  boundary list in code). Unique on (bucket, resolution, instance, method, route)
  so flushes upsert-add. RLS enabled, **no policies** — service_role only, exactly
  like `error_groups` (server-level admin data).

## Coupling

- No domain events needed: `RequestLogger` → accumulator is a shared-internal call;
  the metrics context reads the accumulator (contexts may import shared).
- No cross-context imports beyond `auth`/`settings`/`console` contracts, mirroring
  `apps/issues`.
