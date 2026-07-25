-- Load metrics (Metrics-as-Postgres brick): each process flushes aggregated
-- per-minute deltas — one row per (bucket, instance, method, route), NEVER one
-- per request; that ratio is what makes time-series-in-Postgres viable. A daily
-- rollup downsamples minute → hour and applies retention. duration_buckets is
-- positionally aligned with BUCKET_BOUNDS_MS in apps/shared/observability/metrics.py.
-- Server-level admin data: RLS enabled with no policies — same posture as error_groups.
create table public.request_metrics (
  id               uuid primary key default public.uuidv7(),
  bucket           timestamptz not null,
  resolution       text not null default 'minute',
  instance         text not null,
  method           text not null,
  route            text not null,
  requests         bigint not null default 0,
  errors           bigint not null default 0,
  duration_sum_ms  double precision not null default 0,
  duration_buckets integer[] not null,
  created_at       timestamptz not null default now()
);

create unique index request_metrics_key
  on public.request_metrics (bucket, resolution, instance, method, route);
create index request_metrics_window_idx on public.request_metrics (bucket);

alter table public.request_metrics enable row level security;

grant select, insert, update, delete on public.request_metrics to service_role;
