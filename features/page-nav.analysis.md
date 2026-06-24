# Impact analysis — Page navigation

## Goal
Allow owners to curate a navigation menu for their org's published pages. The nav
is displayed to readers (members and anonymous visitors) when browsing pages.

## New data

New `page_nav_items` table (owned by this context):

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `org_id` | UUID FK → organizations(id) | RLS scope, `on delete cascade` |
| `page_id` | UUID FK → pages(id) | `on delete cascade` |
| `position` | FLOAT | linked-list order, same pattern as todos |

Unique `(org_id, page_id)` — a page appears at most once in the nav.

Only published pages (`members` or `public`) can be added. If a page is
unpublished back to draft, cascade delete removes it from nav automatically
(FK on delete cascade).

## New domain model & service

`apps/pages/domain/models.py` — add `PageNavItem` ORM model + `PageNavItemRead`.

`apps/pages/domain/nav_service.py` (new) — encapsulates:
- `list_nav(org_id, visibility_filter)` — ordered nav items
- `add_to_nav(org_id, page_id)` — appends at end
- `remove_from_nav(org_id, page_id)` — deletes
- `reorder(org_id, page_id, above_id)` — same float-position trick as todos

## New routes (added to `apps/pages/infra/router.py`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/pages/nav` | owner | nav manager UI |
| POST | `/pages/nav` | owner | add page to nav |
| DELETE | `/pages/nav/{page_id}` | owner | remove page from nav |
| PUT | `/pages/nav/{page_id}/position` | owner | reorder |

Public nav data is fetched inline in the existing `view_page` and `list_pages`
routes (no new public endpoint needed).

## Templates

- `pages/nav.html` — owner management UI (todo-style: drag handle + checkbox per row)
- `pages/view_public.html` — updated: adds a sidebar with public nav items, replacing
  the minimal breadcrumb header for visitors (layout becomes logo + pages sidebar + content)
- `pages/public_list.html` — updated similarly with the same sidebar
- `pages/view.html` — passes `page_nav_links` (members + public nav items for the org)
  into the template context; `base.html` renders them in the dark sidebar below the
  static `nav_items` for the current org, as individual page links
- `apps/shared/templates/base.html` — minor addition: after the `nav_items` loop, render
  `page_nav_links` if present in context (a list of `{title, slug}` dicts)

## Cross-context impact

- `apps/pages/infra/repository.py`: add `PageNavRepository`
- Supabase migration: new `page_nav_items` table + RLS policies
- No other contexts are affected

## Permissions

| Action | Who |
|--------|-----|
| Manage nav (add / remove / reorder) | Owner only |
| View nav (in page rendering) | Anyone who can view the page |
| See members-only nav items | Authenticated members only |
