-- Demo app — trivial CRUD wired to every surface, and the reference for building your own.
-- Delete this file with apps/todo/ when real work starts.

create table public.todos (
  id         uuid        primary key default public.uuidv7(),
  org_id     uuid        not null references public.organizations(id) on delete cascade,
  user_id    uuid        not null references auth.users(id) on delete cascade
                         deferrable initially immediate,
  title      text        not null,
  done       boolean     not null default false,
  position   integer     not null default 0,
  version    integer     not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index todos_org_position_idx on public.todos (org_id, position);

create trigger todos_updated_at
  before update on public.todos
  for each row execute procedure public.set_updated_at();

alter table public.todos enable row level security;

create policy "todos: member all"
  on public.todos for all
  using (org_id in (select public.user_org_ids()))
  with check (org_id in (select public.user_org_ids()));

grant select, insert, update, delete on public.todos to authenticated;
grant select, insert, update, delete on public.todos to service_role;


-- A server-owned aggregate maintained by a durable async consumer of `todo.ticked` — the demo of
-- outbox event fan-out. Members read their org's tally on the dashboard; only the consumer (admin
-- session) writes it, so there is no authenticated write grant and a member cannot inflate it.
create table public.todo_completion_stats (
  org_id          uuid        primary key references public.organizations(id) on delete cascade,
  completed_count integer     not null default 0,
  updated_at      timestamptz not null default now()
);

alter table public.todo_completion_stats enable row level security;

create policy "todo_completion_stats: member read"
  on public.todo_completion_stats for select
  using (org_id in (select public.user_org_ids()));

grant select on public.todo_completion_stats to authenticated;
grant select, insert, update on public.todo_completion_stats to service_role;
