create table public.todos (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  org_id     uuid not null references public.organizations(id) on delete cascade,
  title      text not null,
  done       boolean not null default false,
  position   integer not null default 0,
  version    integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger todos_updated_at
  before update on public.todos
  for each row execute procedure public.set_updated_at();

create index todos_org_position on public.todos (org_id, position);

alter table public.todos enable row level security;

create policy "todos: org members"
  on public.todos for all
  using (org_id in (select public.user_orgs()))
  with check (org_id in (select public.user_orgs()));

grant select, insert, update, delete on public.todos to authenticated;
grant select, insert, update, delete on public.todos to service_role;
