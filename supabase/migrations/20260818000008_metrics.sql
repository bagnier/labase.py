-- Load metrics (Metrics-as-Postgres): each process flushes aggregated per-minute deltas — one row
-- per (bucket, instance, method, route), NEVER one per request; that ratio is what makes a time
-- series in Postgres viable. A daily rollup downsamples minute → hour and applies retention.
--
-- Server-level admin data: RLS on with no policy, same posture as `issues`.

create type public.metric_resolution as enum ('minute', 'hour');

create table public.request_metrics (
  id               uuid                     primary key default public.uuidv7(),
  -- The instant the bucket opens. Not just `bucket`: this schema already spends that word on
  -- `duration_buckets` (a histogram) and on Storage buckets.
  bucket_start     timestamptz              not null,
  resolution       public.metric_resolution not null default 'minute',
  instance         text                     not null,
  method           text                     not null,
  route            text                     not null,
  requests         bigint                   not null default 0,
  errors           bigint                   not null default 0,
  duration_sum_ms  double precision         not null default 0,
  -- Positionally aligned with BUCKET_BOUNDS_MS in apps/shared/observability/metrics.py — the shape
  -- Prometheus derives percentiles from, so p95 survives aggregation across rows.
  duration_buckets integer[]                not null,
  created_at       timestamptz              not null default now()
);

create unique index request_metrics_key_idx
  on public.request_metrics (bucket_start, resolution, instance, method, route);
create index request_metrics_bucket_start_idx on public.request_metrics (bucket_start);

alter table public.request_metrics enable row level security;

grant select, insert, update, delete on public.request_metrics to service_role;
