-- Make org and request first-class on the audit trail so the unified logs viewer
-- (apps/logs) can filter by org and correlate an audit row with its request / firehose
-- line. Until now org_id lived only inside `payload` (unindexed) and request_id was
-- absent from the persisted row. Nullable + backfill-free: old rows keep payload.org_id.
alter table public.audit_logs add column org_id     uuid;
alter table public.audit_logs add column request_id text;

create index audit_logs_org_id_idx     on public.audit_logs (org_id) where org_id is not null;
create index audit_logs_request_id_idx on public.audit_logs (request_id) where request_id is not null;
