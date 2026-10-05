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
  -- Full-text search over title and body; a constant regconfig keeps it immutable.
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

-- Members read every page and write drafts; publishing takes an owner.
-- `to authenticated`: anon holds no EXECUTE on the helpers.
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


-- ── What a visitor outside the org reads ────────────────────────────────────────────────────────
--
-- Its public pages and their nav items, on the RLS connection. `app_rls` alone: PostgREST keeps
-- the column-limited `pages: anon read`.

create function public.public_pages(p_org_id uuid)
returns setof public.pages language sql stable security definer set search_path = '' as $$
  select * from public.pages where org_id = p_org_id and visibility = 'public'
$$;

create function public.public_nav_items(p_org_id uuid)
returns setof public.page_nav_items language sql stable security definer set search_path = '' as $$
  select n.* from public.page_nav_items n
    join public.pages p on p.id = n.page_id
   where n.org_id = p_org_id and p.visibility = 'public'
$$;

revoke all on function public.public_pages(uuid), public.public_nav_items(uuid) from public;
grant execute on function public.public_pages(uuid), public.public_nav_items(uuid) to app_rls;
