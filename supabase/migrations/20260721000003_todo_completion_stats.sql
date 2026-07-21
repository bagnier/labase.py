-- Per-org cumulative todo-completion counter — a server-owned aggregate maintained by a durable
-- async consumer of `todo.ticked` (demonstrates the outbox event fan-out). Members read their
-- org's tally on the dashboard; only the consumer (admin/BYPASSRLS session) writes it, so no
-- authenticated write grant — a member cannot inflate the count, exactly like business_events.
create table public.todo_completion_stats (
  org_id     uuid        primary key references public.organizations(id) on delete cascade,
  completed  integer     not null default 0,
  updated_at timestamptz not null default now()
);

alter table public.todo_completion_stats enable row level security;

create policy "todo_completion_stats: org members read"
  on public.todo_completion_stats for select
  using (org_id in (select public.user_orgs()));

grant select on public.todo_completion_stats to authenticated;
grant select, insert, update on public.todo_completion_stats to service_role;
