create table public.page_nav_items (
  id       uuid primary key default gen_random_uuid(),
  org_id   uuid not null references public.organizations(id) on delete cascade,
  page_id  uuid not null references public.pages(id) on delete cascade,
  position integer not null default 0,
  unique (org_id, page_id)
);

create index page_nav_items_org on public.page_nav_items (org_id, position);

alter table public.page_nav_items enable row level security;

create policy "page_nav_items: org members"
  on public.page_nav_items for all
  using  (org_id in (select public.user_orgs()))
  with check (org_id in (select public.user_orgs()));

grant select, insert, update, delete on public.page_nav_items to authenticated;
