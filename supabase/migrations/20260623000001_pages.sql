create table public.pages (
  id          uuid primary key default gen_random_uuid(),
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
