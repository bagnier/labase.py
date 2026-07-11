import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.current import CurrentUser, OptionalCurrentUser, RlsSession
from apps.organizations.contract.current import (
    CurrentMembership,
    CurrentOrg,
    CurrentOrgModel,
    Membership,
    OrganizationRead,
    OrgRole,
)
from apps.organizations.contract.queries import org_by_handle, role_in_org
from apps.pages.domain.models import NavItemRead, Page, PageRead, PageVisibility
from apps.pages.domain.render import render_markdown
from apps.pages.infra.repository import (
    PageNavRepository,
    PageRepository,
    search_visible_pages,
    visible_pages,
)
from apps.shared.http import (
    delete_response,
    mutation_response,
    or_404,
    parse_body,
    wants_json,
    with_etag,
)
from apps.shared.http.templates import templates
from apps.shared.observability.audit import audit
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession
from apps.shared.slug_registry import slugify

router = APIRouter(prefix="/pages", tags=["pages"])
public_router = APIRouter(tags=["pages"])


async def _get_repo(session: RlsSession, org_id: CurrentOrg) -> PageRepository:
    return PageRepository(session, org_id)


PageRepo = Annotated[PageRepository, Depends(_get_repo)]


def _can_edit_role(visibility: PageVisibility, role: OrgRole | None) -> bool:
    """Drafts are collaborative (any member); once published, only owners may change them."""
    return role == OrgRole.owner or (role is not None and visibility == PageVisibility.draft)


def _can_view(visibility: PageVisibility, role: OrgRole | None) -> bool:
    return visibility == PageVisibility.public or role is not None


async def _editable_page(repo: PageRepository, slug: str, membership: Membership) -> Page:
    page = or_404(await repo.by_slug(slug))
    if not _can_edit_role(page.visibility, membership.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This page is read-only")
    return page


def _require_nav_owner(membership: Membership) -> None:
    if membership.role != OrgRole.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can manage navigation")


def _parse_visibility(value: str) -> PageVisibility:
    try:
        return PageVisibility(value)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid visibility") from None


async def _resolve_org_role(
    admin: AsyncSession,
    rls: AsyncSession,
    org_handle: str,
    current_user: OptionalCurrentUser,
) -> tuple[OrganizationRead, OrgRole | None, AsyncSession]:
    """The org, the caller's role in it (``None`` if anonymous/non-member), and the session to
    read pages with — RLS for members, admin (BYPASSRLS) for the public/anonymous view."""
    org = or_404(await org_by_handle(admin, org_handle))
    role = await role_in_org(rls, org.id, uuid.UUID(current_user.id)) if current_user else None
    session = rls if role is not None else admin
    return org, role, session


# ── authed management routes (mounted under /{org_handle}, RLS) ────────────────


@router.post("")
async def create_page(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    membership: CurrentMembership,
    repo: PageRepo,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
) -> Response:
    body = await parse_body(request)
    title = str(body.get("title", "")).strip()
    if not title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Title is required")
    content = str(body.get("content", ""))
    slug = slugify(str(body.get("slug", "")) or title) or "page"
    if await repo.slug_taken(slug):
        raise HTTPException(status.HTTP_409_CONFLICT, "A page with this slug already exists")
    page = await repo.add(uuid.UUID(current_user.id), title, slug, content)
    audit(
        bg,
        "pages.created",
        user_id=current_user.id,
        org_id=org_id,
        slug=slug,
    )
    if wants_json(request):
        return JSONResponse(PageRead.model_validate(page).model_dump(mode="json"), status_code=201)
    return RedirectResponse(f"/{org.handle}/pages/{slug}/edit", status_code=303)


@router.get("/new/edit")
async def new_page(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    _membership: CurrentMembership,
    repo: PageRepo,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
) -> Response:
    base = "page"
    slug = base
    counter = 2
    while await repo.slug_taken(slug):
        slug = f"{base}-{counter}"
        counter += 1
    title = "New page"
    await repo.add(uuid.UUID(current_user.id), title, slug, "")
    audit(
        bg,
        "pages.created",
        user_id=current_user.id,
        org_id=org_id,
        slug=slug,
    )
    return RedirectResponse(f"/{org.handle}/pages/{slug}/edit", status_code=303)


@router.get("/{slug}/edit", response_class=HTMLResponse)
async def edit_page(
    request: Request,
    slug: str,
    current_user: CurrentUser,
    membership: CurrentMembership,
    session: RlsSession,
    repo: PageRepo,
    org: CurrentOrgModel,
) -> Response:
    page = await _editable_page(repo, slug, membership)
    ctx = await fullpage_context(
        session,
        current_user,
        page=page,
        org=org,
        org_handle=org.handle,
        is_owner=membership.role == OrgRole.owner,
    )
    return templates.TemplateResponse(request, "pages/form.html", ctx)


@router.patch("/{slug}")
async def update_page(
    request: Request,
    bg: BackgroundTasks,
    slug: str,
    current_user: CurrentUser,
    membership: CurrentMembership,
    repo: PageRepo,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
) -> Response:
    page = await _editable_page(repo, slug, membership)
    body = await parse_body(request)
    event = "pages.updated"
    new_slug = body.get("slug")
    if new_slug is not None:
        normalized = slugify(str(new_slug)) or page.slug
        if normalized != page.slug:
            if await repo.slug_taken(normalized, exclude_id=page.id):
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "A page with this slug already exists"
                )
            page.slug = normalized
            event = "pages.slug_changed"
    if body.get("content") is not None:
        page.content = str(body["content"])
    if body.get("title") is not None:
        page.title = str(body["title"]).strip() or page.title
    if body.get("visibility") is not None:
        visibility = _parse_visibility(str(body["visibility"]))
        if visibility != page.visibility:
            if membership.role != OrgRole.owner:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "Only owners can change a page's visibility"
                )
            page.visibility = visibility
            event = _PUBLISH_EVENT[visibility]
    await repo.save(page)
    audit(
        bg,
        event,
        user_id=current_user.id,
        org_id=org_id,
        slug=page.slug,
    )
    # The edit form submits via HTMX: send the browser to the (possibly re-slugged)
    # page so the save lands on visible, rendered output instead of a silent swap.
    return mutation_response(
        request,
        obj=PageRead.model_validate(page),
        redirect_url=f"/{org.handle}/pages",
        htmx_redirect_url=f"/{org.handle}/pages/{page.slug}",
    )


@router.delete("/{slug}")
async def delete_page(
    request: Request,
    bg: BackgroundTasks,
    slug: str,
    current_user: CurrentUser,
    membership: CurrentMembership,
    repo: PageRepo,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
) -> Response:
    page = await _editable_page(repo, slug, membership)
    await repo.delete(page)
    audit(
        bg,
        "pages.deleted",
        user_id=current_user.id,
        org_id=org_id,
        slug=slug,
    )
    # Deleting from the edit page (HTMX) sends the browser back to the list; deleting
    # from a list row (X-Skip-Redirect) stays put and removes just that row client-side.
    htmx_redirect_url = None
    if request.headers.get("X-Skip-Redirect") != "true":
        htmx_redirect_url = f"/{org.handle}/pages"
    return delete_response(request, htmx_redirect_url=htmx_redirect_url)


_PUBLISH_EVENT = {
    PageVisibility.draft: "pages.unpublished",
    PageVisibility.members: "pages.published_members",
    PageVisibility.public: "pages.published_public",
}


@router.post("/{slug}/visibility")
async def set_visibility(
    request: Request,
    bg: BackgroundTasks,
    slug: str,
    current_user: CurrentUser,
    membership: CurrentMembership,
    repo: PageRepo,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
) -> Response:
    if membership.role != OrgRole.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can change a page's visibility")
    page = or_404(await repo.by_slug(slug))
    body = await parse_body(request)
    visibility = _parse_visibility(str(body.get("visibility")))
    page.visibility = visibility
    await repo.save(page)
    audit(
        bg,
        _PUBLISH_EVENT[visibility],
        user_id=current_user.id,
        org_id=org_id,
        slug=slug,
    )
    return mutation_response(
        request, obj=PageRead.model_validate(page), redirect_url=f"/{org.handle}/pages"
    )


async def _get_nav_repo(session: RlsSession, org_id: CurrentOrg) -> PageNavRepository:
    return PageNavRepository(session, org_id)


PageNavRepo = Annotated[PageNavRepository, Depends(_get_nav_repo)]


@router.get("/nav", response_class=HTMLResponse)
async def nav_manager(
    request: Request,
    current_user: CurrentUser,
    membership: CurrentMembership,
    session: RlsSession,
    nav_repo: PageNavRepo,
    org: CurrentOrgModel,
) -> Response:
    _require_nav_owner(membership)
    candidates = await nav_repo.candidates()
    if wants_json(request):
        return JSONResponse([c.model_dump(mode="json") for c in candidates])
    ctx = await fullpage_context(
        session,
        current_user,
        candidates=candidates,
        org=org,
        org_handle=org.handle,
    )
    return templates.TemplateResponse(request, "pages/nav.html", ctx)


@router.post("/nav")
async def add_to_nav(
    request: Request,
    membership: CurrentMembership,
    repo: PageRepo,
    nav_repo: PageNavRepo,
    org: CurrentOrgModel,
) -> Response:
    _require_nav_owner(membership)
    body = await parse_body(request)
    slug = str(body.get("slug", "")).strip()
    page = or_404(await repo.by_slug(slug))
    if page.visibility == PageVisibility.draft:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Draft pages cannot be added to navigation"
        )
    await nav_repo.add(page.id)
    item = NavItemRead(
        page_id=page.id, slug=page.slug, title=page.title, visibility=page.visibility
    )
    return mutation_response(
        request, obj=item, redirect_url=f"/{org.handle}/pages/nav", status_code=201
    )


@router.delete("/nav/{slug}")
async def remove_from_nav(
    request: Request,
    slug: str,
    membership: CurrentMembership,
    repo: PageRepo,
    nav_repo: PageNavRepo,
    org: CurrentOrgModel,
) -> Response:
    _require_nav_owner(membership)
    page = or_404(await repo.by_slug(slug))
    await nav_repo.remove(page.id)
    if wants_json(request):
        return delete_response(request)
    return RedirectResponse(f"/{org.handle}/pages/nav", status_code=303)


@router.put("/nav/{slug}/position")
async def reorder_nav(
    request: Request,
    slug: str,
    membership: CurrentMembership,
    repo: PageRepo,
    nav_repo: PageNavRepo,
) -> Response:
    _require_nav_owner(membership)
    body = await parse_body(request)
    page = or_404(await repo.by_slug(slug))
    above_slug = body.get("above_slug")
    above_id: uuid.UUID | None = None
    if above_slug:
        above_page = await repo.by_slug(str(above_slug))
        if above_page:
            above_id = above_page.id
    await nav_repo.move_above(page.id, above_id)
    item = NavItemRead(
        page_id=page.id, slug=page.slug, title=page.title, visibility=page.visibility
    )
    return JSONResponse(item.model_dump(mode="json"))


# ── public-capable routes (root-mounted; serve members and anon visitors) ──────


@public_router.get("/{org_handle}/pages", response_class=HTMLResponse)
async def list_pages(
    request: Request,
    org_handle: str,
    admin: AdminSession,
    rls: RlsSession,
    current_user: OptionalCurrentUser,
) -> Response:
    org, role, session = await _resolve_org_role(admin, rls, org_handle, current_user)
    query = request.query_params.get("q", "").strip()
    if query:
        pages = await search_visible_pages(session, org.id, query, role=role)
    else:
        pages = await visible_pages(session, org.id, role=role)
    if wants_json(request):
        return JSONResponse([PageRead.model_validate(p).model_dump(mode="json") for p in pages])
    if current_user is None:
        return with_etag(
            request,
            templates.TemplateResponse(
                request,
                "pages/public_list.html",
                {"pages": pages, "org": org, "org_handle": org_handle},
            ),
        )
    pages_data = [
        {
            "id": str(p.id),
            "title": p.title,
            "slug": p.slug,
            "visibility": str(p.visibility),
            "created": p.created_at.isoformat(),
            "updated": p.updated_at.isoformat(),
        }
        for p in pages
    ]
    ctx = await fullpage_context(
        rls,
        current_user,
        pages=pages,
        pages_data=pages_data,
        org=org,
        org_handle=org_handle,
        can_create=role is not None,
        is_owner=role == OrgRole.owner,
        search_query=query,
    )
    return with_etag(request, templates.TemplateResponse(request, "pages/pages.html", ctx))


@public_router.get("/{org_handle}/pages/{slug}", response_class=HTMLResponse)
async def view_page(
    request: Request,
    org_handle: str,
    slug: str,
    admin: AdminSession,
    rls: RlsSession,
    current_user: OptionalCurrentUser,
) -> Response:
    org, role, session = await _resolve_org_role(admin, rls, org_handle, current_user)
    page = or_404(await PageRepository(session, org.id).by_slug(slug))
    if not _can_view(page.visibility, role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This page is not available")
    can_edit = _can_edit_role(page.visibility, role)
    body = render_markdown(page.content)
    if current_user:
        ctx = await fullpage_context(
            rls,
            current_user,
            page=page,
            body=body,
            can_edit=can_edit,
            org=org,
            org_handle=org_handle,
        )
        return with_etag(request, templates.TemplateResponse(request, "pages/view.html", ctx))
    return with_etag(
        request,
        templates.TemplateResponse(
            request,
            "pages/view_public.html",
            {
                "page": page,
                "body": body,
                "can_edit": can_edit,
                "org_handle": org_handle,
                "org": org,
            },
        ),
    )
