# Impact analysis — CMS pages

## Bounded context
A new standalone context `apps/pages/`. It owns its data entirely and mirrors the
`apps/todo/` and `apps/files/` modules (mount entry, settings switch, NavItem,
dashboard + console overviews, audit events).

## Data
New `pages` table:

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | `gen_random_uuid()` |
| `org_id` | UUID FK → organizations(id) | RLS scope, `on delete cascade` |
| `user_id` | UUID | author (auth.users.id) |
| `title` | TEXT | shown as the page H1 — never duplicated in `content` |
| `slug` | TEXT | URL segment; editable; `slugify`'d default from title |
| `content` | TEXT | Markdown **body only** |
| `visibility` | TEXT | enum `draft` / `members` / `public` (increasing) |
| `version` | INTEGER | optimistic lock (`version_id_col`) |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | trigger |

Unique `(org_id, slug)`. Per-org slug uniqueness via this constraint + a repo
pre-check — **not** the global handle registry (page slugs are org-scoped, only
the literal `pages` URL segment is reserved with `host.reserve`).

## Permissions
| Role / state | draft | members | public |
|---|---|---|---|
| Visitor (anon) | — | — | read |
| Member | full CRUD | read | read |
| Owner | full CRUD | full CRUD | full CRUD |

- Only owners change visibility (the "switches"); guarded by `CurrentOwnerMembership`.
- Once visibility ≥ `members`, only owners may edit/delete/re-slug.

## Routing
- Management (RLS, authed): `router = APIRouter(prefix="/pages")` mounted under
  `ORG_PREFIX` — list / new / create / edit / update / delete / visibility toggle.
- Public view (anon-capable): `public_router = APIRouter(prefix="/pages")` mounted
  at app root, GET `/{org_handle}/pages/{slug}`. Resolves the org by handle via an
  `AdminSession` lookup (no RLS); enforces visibility — `public` → anyone,
  `members`/`draft` → must be an authenticated member, else 403/404. This avoids a
  redirect-to-signin for visitors while keeping member CRUD RLS-protected.

## Markdown rendering
No markdown lib exists today. Add `mistune` (MD→HTML) + `nh3` (sanitize) to
`pyproject.toml`. `apps/pages/domain/render.py::render_markdown(md) -> str`
encapsulates convert+sanitize so it can be swapped. Output rendered with
`{{ html|safe }}`; sanitization is mandatory (anon-facing, user-authored → XSS).

## Cross-context wiring (no shared data)
- `OverviewQuery` → org dashboard card (`apps/pages/templates/pages/_overview.html`).
- `ConsoleOverviewQuery` → server-wide console card; wired even when disabled.
- `SettingsChanged` → reload cached settings.
- `declare_app_settings("pages", [feature_switch(), default_visibility, …],
  supabase=SupabaseLink(table="pages"))` — editable on the console settings page.
- Optional `OrgCreated` → seed a welcome page.

## Observability
`record_audit_event` on every mutation: `pages.created`, `pages.updated`,
`pages.slug_changed`, `pages.deleted`, `pages.published_members`,
`pages.published_public`, `pages.unpublished`. Reads not audited.

## Affected existing files
| File | Change |
|------|--------|
| `tests/plugin.py` | add `apps.pages.tests.e2e.steps` |
| `tests/e2e/drivers/api.py`, `browser.py` | add `Pages*Mixin` to MRO |
| `tests/e2e/drivers/protocols.py` | extend protocol |
| `apps/main.py` | register `apps.pages` context |
| `pyproject.toml` | add `mistune`, `nh3` |
