-- Add slug to organizations for readable URLs (/orgs/{slug}/...)
-- Slug is derived from name at creation time and never changes on rename.

alter table public.organizations add column if not exists slug text not null default '';

-- Backfill: generate unique slug per org using id suffix to avoid collisions
update public.organizations
set slug = lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g'))
        || '-' || substring(id::text, 1, 8)
where slug = '';

create unique index if not exists organizations_slug_unique on public.organizations (slug);
