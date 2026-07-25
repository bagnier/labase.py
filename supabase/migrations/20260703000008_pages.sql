create table public.pages (
  id          uuid primary key default public.uuidv7(),
  org_id      uuid not null references public.organizations(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  title       text not null,
  slug        text not null,
  content     text not null default '',
  visibility  text not null default 'draft' check (visibility in ('draft', 'members', 'public')),
  version     integer not null default 1,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (org_id, slug)
);

create trigger pages_updated_at
  before update on public.pages
  for each row execute procedure public.set_updated_at();

create index pages_org on public.pages (org_id, created_at desc);

alter table public.pages enable row level security;

-- Members manage their organisation's pages (drafts are collaborative). Owner-only
-- rules for published pages are enforced in the application layer.
create policy "pages: org members"
  on public.pages for all
  using  (org_id in (select public.user_orgs()))
  with check (org_id in (select public.user_orgs()));

-- Anonymous visitors may read pages explicitly published to the public.
create policy "pages: public read"
  on public.pages for select
  to anon
  using (visibility = 'public');

grant select, insert, update, delete on public.pages to authenticated;
grant select on public.pages to anon;
grant select, insert, update, delete on public.pages to service_role;

create table public.page_nav_items (
  id         uuid primary key default public.uuidv7(),
  org_id     uuid not null references public.organizations(id) on delete cascade,
  page_id    uuid not null references public.pages(id) on delete cascade,
  position   integer not null default 0,
  version    integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (org_id, page_id)
);

create trigger page_nav_items_updated_at
  before update on public.page_nav_items
  for each row execute procedure public.set_updated_at();

create index page_nav_items_org on public.page_nav_items (org_id, position);

alter table public.page_nav_items enable row level security;

create policy "page_nav_items: org members"
  on public.page_nav_items for all
  using  (org_id in (select public.user_orgs()))
  with check (org_id in (select public.user_orgs()));

grant select, insert, update, delete on public.page_nav_items to authenticated;
grant select, insert, update, delete on public.page_nav_items to service_role;
