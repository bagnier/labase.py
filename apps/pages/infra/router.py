import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from apps.auth.contract.current import CurrentUser, OptionalCurrentUser, RlsSession
from apps.organizations.contract.current import (
    CurrentMembership,
    CurrentOrg,
    CurrentOrgModel,
    Membership,
    OrgRole,
)
from apps.pages.domain.models import Page, PageRead, PageVisibility
from apps.pages.domain.render import render_markdown
from apps.pages.infra.repository import (
    PageRepository,
    org_by_handle,
    role_in_org,
    visible_pages,
)
from apps.profile.contract.shell import page_context
from apps.shared.http import or_404, parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.observability.audit import record_audit_event
from apps.shared.persistence.database import AdminSession
from apps.shared.slug_registry import slugify

router = APIRouter(prefix="/pages", tags=["pages"])
public_router = APIRouter(tags=["pages"])


async def _get_repo(session: RlsSession, org_id: CurrentOrg) -> PageRepository:
    return PageRepository(session, org_id)


PageRepo = Annotated[PageRepository, Depends(_get_repo)]


def _can_edit(page: Page, membership: Membership) -> bool:
    """Drafts are collaborative (any member); once published, only owners may change them."""
    return membership.role == OrgRole.owner or page.visibility == PageVisibility.draft


def _can_view(visibility: PageVisibility, role: OrgRole | None) -> bool:
    return visibility == PageVisibility.public or role is not None


def _mutation_response(request: Request, org_handle: str) -> Response:
    if wants_json(request):
        return JSONResponse({"ok": True})
    return RedirectResponse(f"/{org_handle}/pages", status_code=303)


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
        raise HTTPException(422, "Title is required")
    content = str(body.get("content", ""))
    slug = slugify(str(body.get("slug", "")) or title) or "page"
    if await repo.slug_taken(slug):
        raise HTTPException(409, "A page with this slug already exists")
    page = await repo.add(uuid.UUID(current_user.id), title, slug, content)
    record_audit_event(
        bg,
        level="info",
        event="pages.created",
        user_id=current_user.id,
        org_id=str(org_id),
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
    record_audit_event(
        bg,
        level="info",
        event="pages.created",
        user_id=current_user.id,
        org_id=str(org_id),
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
    page = or_404(await repo.by_slug(slug))
    if not _can_edit(page, membership):
        raise HTTPException(403, "This page is read-only")
    ctx = await page_context(
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
    page = or_404(await repo.by_slug(slug))
    if not _can_edit(page, membership):
        raise HTTPException(403, "This page is read-only")
    body = await parse_body(request)
    event = "pages.updated"
    new_slug = body.get("slug")
    if new_slug is not None:
        normalized = slugify(str(new_slug)) or page.slug
        if normalized != page.slug:
            if await repo.slug_taken(normalized, exclude_id=page.id):
                raise HTTPException(409, "A page with this slug already exists")
            page.slug = normalized
            event = "pages.slug_changed"
    if body.get("content") is not None:
        page.content = str(body["content"])
    if body.get("title") is not None:
        page.title = str(body["title"]).strip() or page.title
    if body.get("visibility") is not None:
        try:
            visibility = PageVisibility(str(body["visibility"]))
        except ValueError:
            raise HTTPException(422, "Invalid visibility") from None
        if visibility != page.visibility:
            if membership.role != OrgRole.owner:
                raise HTTPException(403, "Only owners can change a page's visibility")
            page.visibility = visibility
            event = _PUBLISH_EVENT[visibility]
    await repo.save(page)
    record_audit_event(
        bg,
        level="info",
        event=event,
        user_id=current_user.id,
        org_id=str(org_id),
        slug=page.slug,
    )
    # The edit form submits via HTMX: send the browser to the (possibly re-slugged)
    # page so the save lands on visible, rendered output instead of a silent swap.
    if request.headers.get("HX-Request") == "true":
        resp = Response(status_code=204)
        resp.headers["HX-Redirect"] = f"/{org.handle}/pages/{page.slug}"
        return resp
    return _mutation_response(request, org.handle)


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
    page = or_404(await repo.by_slug(slug))
    if not _can_edit(page, membership):
        raise HTTPException(403, "This page is read-only")
    await repo.delete(page)
    record_audit_event(
        bg,
        level="info",
        event="pages.deleted",
        user_id=current_user.id,
        org_id=str(org_id),
        slug=slug,
    )
    # Deleting from the edit page (HTMX) → send the browser back to the list.
    if request.headers.get("HX-Request") == "true":
        resp = Response(status_code=204)
        resp.headers["HX-Redirect"] = f"/{org.handle}/pages"
        return resp
    return _mutation_response(request, org.handle)


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
        raise HTTPException(403, "Only owners can change a page's visibility")
    page = or_404(await repo.by_slug(slug))
    body = await parse_body(request)
    try:
        visibility = PageVisibility(str(body.get("visibility")))
    except ValueError:
        raise HTTPException(422, "Invalid visibility") from None
    page.visibility = visibility
    await repo.save(page)
    record_audit_event(
        bg,
        level="info",
        event=_PUBLISH_EVENT[visibility],
        user_id=current_user.id,
        org_id=str(org_id),
        slug=slug,
    )
    return _mutation_response(request, org.handle)


# ── public-capable routes (root-mounted; serve members and anon visitors) ──────


@public_router.get("/{org_handle}/pages", response_class=HTMLResponse)
async def list_pages(
    request: Request,
    org_handle: str,
    admin: AdminSession,
    current_user: OptionalCurrentUser,
) -> Response:
    org = or_404(await org_by_handle(admin, org_handle))
    role = await role_in_org(admin, org.id, uuid.UUID(current_user.id)) if current_user else None
    pages = await visible_pages(admin, org.id, role=role)
    if wants_json(request):
        return JSONResponse([PageRead.model_validate(p).model_dump(mode="json") for p in pages])
    if current_user is None:
        return templates.TemplateResponse(
            request,
            "pages/public_list.html",
            {"pages": pages, "org": org, "org_handle": org_handle},
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
    ctx = await page_context(
        admin,
        current_user,
        pages=pages,
        pages_data=pages_data,
        org=org,
        org_handle=org_handle,
        can_create=role is not None,
        is_owner=role == OrgRole.owner,
    )
    return templates.TemplateResponse(request, "pages/pages.html", ctx)


@public_router.get("/{org_handle}/pages/{slug}", response_class=HTMLResponse)
async def view_page(
    request: Request,
    org_handle: str,
    slug: str,
    admin: AdminSession,
    current_user: OptionalCurrentUser,
) -> Response:
    org = or_404(await org_by_handle(admin, org_handle))
    page = or_404(await PageRepository(admin, org.id).by_slug(slug))
    role = await role_in_org(admin, org.id, uuid.UUID(current_user.id)) if current_user else None
    if not _can_view(page.visibility, role):
        raise HTTPException(403, "This page is not available")
    can_edit = role == OrgRole.owner or (
        role is not None and page.visibility == PageVisibility.draft
    )
    body = render_markdown(page.content)
    if current_user:
        ctx = await page_context(
            admin,
            current_user,
            page=page,
            body=body,
            can_edit=can_edit,
            org_handle=org_handle,
        )
        return templates.TemplateResponse(request, "pages/view.html", ctx)
    return templates.TemplateResponse(
        request,
        "pages/view_public.html",
        {"page": page, "body": body, "can_edit": can_edit, "org_handle": org_handle},
    )
