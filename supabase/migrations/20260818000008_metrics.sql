-- One row per (minute, instance, method, route), never per request; a daily rollup downsamples
-- to hours and applies retention. Admin only: RLS on with no policy.

create type public.metric_resolution as enum ('minute', 'hour');

create table public.request_metrics (
  id               uuid                     primary key default public.uuidv7(),
  -- When the bucket opens; `bucket` already names histograms and Storage.
  bucket_start     timestamptz              not null,
  resolution       public.metric_resolution not null default 'minute',
  instance         text                     not null,
  method           text                     not null,
  route            text                     not null,
  requests         bigint                   not null default 0,
  errors           bigint                   not null default 0,
  duration_sum_ms  double precision         not null default 0,
  -- Aligned with BUCKET_BOUNDS_MS (apps/metrics/domain/accumulator.py): p95 survives summing rows.
  duration_buckets integer[]                not null,
  created_at       timestamptz              not null default now()
);

create unique index request_metrics_key_idx
  on public.request_metrics (bucket_start, resolution, instance, method, route);
create index request_metrics_bucket_start_idx on public.request_metrics (bucket_start);

alter table public.request_metrics enable row level security;

grant select, insert, update, delete on public.request_metrics to service_role;
