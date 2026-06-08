-- Ajouter org_id à todos (obligatoire, avec FK + index)
alter table public.todos
  add column org_id uuid references public.organizations(id) on delete cascade;

-- Remplir org_id pour les lignes existantes via la première org du user
update public.todos t
set org_id = (
  select m.org_id
  from public.memberships m
  where m.auth_user_id = t.user_id
  order by m.created_at
  limit 1
);

-- Supprimer les todos orphelines (user sans org — ne devrait pas arriver en pratique)
delete from public.todos where org_id is null;

alter table public.todos alter column org_id set not null;

create index todos_org_position on public.todos (org_id, position);

-- RLS sur todos
alter table public.todos enable row level security;

create policy "todos: org members"
  on public.todos for all
  using (org_id in (select public.user_orgs()))
  with check (org_id in (select public.user_orgs()));
