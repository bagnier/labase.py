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



-- ── todo_completion_stats ───────────────────────────────────────────────────────────────────
--
-- Completions *ever*, per org — a cumulative tally, not the live `done` count: unticking or
-- deleting a task never takes one back. It cannot be derived from `todos`, so it is materialised
-- here and maintained by the trigger below, inside the very transaction that ticks the task.
--
-- Only the trigger writes it: no write grant to `authenticated`, so a member cannot inflate their
-- org's tally by reaching the table directly.
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
grant select on public.todo_completion_stats to service_role;

-- `security definer` is what lets a member's own session bump the tally without ever holding a
-- write grant on the table.
create or replace function public.bump_todo_completion()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  insert into public.todo_completion_stats (org_id, completed_count)
  values (new.org_id, 1)
  on conflict (org_id) do update
    set completed_count = public.todo_completion_stats.completed_count + 1,
        updated_at = now();
  return new;
end;
$$;

create trigger todos_bump_completion
  after update of done on public.todos
  for each row when (old.done is false and new.done is true)
  execute procedure public.bump_todo_completion();
