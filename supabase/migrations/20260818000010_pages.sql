-- Per-org Markdown pages with a visibility ladder, plus the nav items that surface them.

create type public.page_visibility as enum ('draft', 'members', 'public');

create table public.pages (
  id            uuid                    primary key default public.uuidv7(),
  org_id        uuid                    not null references public.organizations(id) on delete cascade,
  user_id       uuid                    not null references auth.users(id) on delete cascade
                                        deferrable initially immediate,
  title         text                    not null,
  slug          text                    not null,
  content       text                    not null default '',
  visibility    public.page_visibility  not null default 'draft',
  -- Stored generated tsvector across title + body, GIN-indexed; the list screen ranks matches with
  -- ts_rank / websearch_to_tsquery. Immutable expression (constant 'english' regconfig), so it is
  -- valid as a generated column — and never null, since both inputs are coalesced.
  search_vector tsvector                generated always as (
                                          to_tsvector(
                                            'english',
                                            coalesce(title, '') || ' ' || coalesce(content, '')
                                          )
                                        ) stored not null,
  version       integer                 not null default 1,
  created_at    timestamptz             not null default now(),
  updated_at    timestamptz             not null default now(),
  unique (org_id, slug)
);

create index pages_org_created_at_idx on public.pages (org_id, created_at desc);
create index pages_search_vector_idx  on public.pages using gin (search_vector);

create trigger pages_updated_at
  before update on public.pages
  for each row execute procedure public.set_updated_at();

alter table public.pages enable row level security;

-- Members read every page of their org and write its drafts (drafts are collaborative); an owner
-- writes any page, which is what publishing, and changing what is published, takes. The routes
-- answer the same rule with a clean 403.
-- `to authenticated`: anon holds no EXECUTE on the helpers, and has no org anyway.
create policy "pages: member read"
  on public.pages for select
  to authenticated
  using (org_id in (select public.user_org_ids()));

create policy "pages: member drafts, owner all"
  on public.pages for all
  to authenticated
  using (
    org_id in (select public.user_org_ids())
    and (visibility = 'draft' or public.user_is_org_owner(org_id))
  )
  with check (
    org_id in (select public.user_org_ids())
    and (visibility = 'draft' or public.user_is_org_owner(org_id))
  );

-- Anonymous visitors may read pages explicitly published to the public.
create policy "pages: anon read"
  on public.pages for select
  to anon
  using (visibility = 'public');

grant select, insert, update, delete on public.pages to authenticated;
-- Column by column: what a public page shows, not which org or author it belongs to.
grant select (id, title, slug, content, visibility, created_at, updated_at) on public.pages to anon;
grant select, insert, update, delete on public.pages to service_role;


create table public.page_nav_items (
  id         uuid        primary key default public.uuidv7(),
  org_id     uuid        not null references public.organizations(id) on delete cascade,
  page_id    uuid        not null references public.pages(id) on delete cascade,
  position   integer     not null default 0,
  version    integer     not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (org_id, page_id)
);

create index page_nav_items_org_position_idx on public.page_nav_items (org_id, position);

create trigger page_nav_items_updated_at
  before update on public.page_nav_items
  for each row execute procedure public.set_updated_at();

alter table public.page_nav_items enable row level security;

create policy "page_nav_items: member read"
  on public.page_nav_items for select
  to authenticated
  using (org_id in (select public.user_org_ids()));

create policy "page_nav_items: owner all"
  on public.page_nav_items for all
  to authenticated
  using (public.user_is_org_owner(org_id))
  with check (public.user_is_org_owner(org_id));

grant select, insert, update, delete on public.page_nav_items to authenticated;
grant select, insert, update, delete on public.page_nav_items to service_role;
