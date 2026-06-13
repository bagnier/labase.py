-- todos.org_id FK and RLS policy are added in 000004 after organizations + user_orgs() exist
create table public.todos (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  org_id     uuid not null,
  title      text not null,
  done       boolean not null default false,
  position   integer not null default 0,
  version    integer not null default 1,
  created_at timestamptz not null default now()
);

create index todos_org_position on public.todos (org_id, position);

alter table public.todos enable row level security;

grant select, insert, update, delete on public.todos to authenticated;
