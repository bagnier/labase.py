import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.auth.infra.session import get_rls_session
from app.files.domain.models import OrgFileRead
from app.files.infra.repository import OrgFileRepository
from app.files.infra.storage import (
    BUCKET,
    service_storage_client,
    storage_path,
    user_storage_client,
)
from app.organizations.domain.models import Membership, OrgRole
from app.organizations.infra.context import get_current_membership, get_current_org
from app.shared.http.templates import templates
from app.shared.observability.audit import record_audit_event
from app.shared.persistence.database import get_admin_session

router = APIRouter(prefix="/files", tags=["files"])
public_router = APIRouter(prefix="/files", tags=["files"])

_MAX_SIZE_BYTES = 50 * 1024 * 1024
_SIGNED_URL_TTL = 60


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _html_template(request: Request) -> str:
    return "files/_list_fragment.html" if _is_htmx(request) else "files/list.html"


def _can_modify(file_user_id: uuid.UUID, membership: Membership) -> bool:
    return file_user_id == membership.auth_user_id or membership.role == OrgRole.owner


def _template_ctx(request: Request, current_user: object, files: list) -> dict:
    org_slug = request.path_params.get("org_slug", "")
    return {"user": current_user, "files": files, "org_slug": org_slug}


@router.get("", response_class=HTMLResponse)
async def file_list(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    repo = OrgFileRepository(session)
    files = await repo.list_for_org(org_id)
    if _wants_json(request):
        return JSONResponse([OrgFileRead.model_validate(f).model_dump(mode="json") for f in files])
    return templates.TemplateResponse(
        request, _html_template(request), _template_ctx(request, current_user, files)
    )


@router.post("", response_class=HTMLResponse)
async def upload_file(
    request: Request,
    bg: BackgroundTasks,
    file: UploadFile,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    content = await file.read()
    if len(content) > _MAX_SIZE_BYTES:
        if _wants_json(request):
            return JSONResponse({"detail": "File too large"}, status_code=413)
        return HTMLResponse("File too large", status_code=413)

    file_id = uuid.uuid4()
    path = storage_path(org_id, file_id, file.filename or "upload")
    content_type = file.content_type or "application/octet-stream"

    storage = user_storage_client(current_user.access_token)
    await storage.from_(BUCKET).upload(path, content, {"content-type": content_type})

    repo = OrgFileRepository(session)
    org_file = await repo.add(
        org_id=org_id,
        user_id=uuid.UUID(current_user.id),
        filename=file.filename or "upload",
        storage_path=path,
        content_type=content_type,
        size_bytes=len(content),
        uploader_email=current_user.email,
    )
    record_audit_event(
        bg,
        level="info",
        event="file.uploaded",
        user_id=current_user.id,
        org_id=str(org_id),
        file_id=str(org_file.id),
        filename=org_file.filename,
    )

    files = await repo.list_for_org(org_id)
    if _wants_json(request):
        return JSONResponse([OrgFileRead.model_validate(f).model_dump(mode="json") for f in files])
    return templates.TemplateResponse(
        request, _html_template(request), _template_ctx(request, current_user, files)
    )


@router.get("/{file_id}/download")
async def download_file(
    file_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    repo = OrgFileRepository(session)
    org_file = await repo.get(file_id, org_id)
    if org_file is None:
        return HTMLResponse("Not found", status_code=404)

    storage = user_storage_client(current_user.access_token)
    result = await storage.from_(BUCKET).create_signed_url(org_file.storage_path, _SIGNED_URL_TTL)
    signed_url = result.get("signedURL") or result.get("signedUrl") or ""
    return RedirectResponse(url=signed_url, status_code=302)


@router.delete("/{file_id}", response_class=HTMLResponse)
async def delete_file(
    request: Request,
    bg: BackgroundTasks,
    file_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    org_id: uuid.UUID = Depends(get_current_org),
    membership: Membership = Depends(get_current_membership),
):
    repo = OrgFileRepository(session)
    org_file = await repo.get(file_id, org_id)
    if org_file is None:
        return HTMLResponse("Not found", status_code=404)

    if not _can_modify(org_file.user_id, membership):
        if _wants_json(request):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        return HTMLResponse("Forbidden", status_code=403)

    storage = user_storage_client(current_user.access_token)
    await storage.from_(BUCKET).remove([org_file.storage_path])
    await repo.delete(org_file)
    record_audit_event(
        bg,
        level="info",
        event="file.deleted",
        user_id=current_user.id,
        org_id=str(org_id),
        file_id=str(file_id),
    )

    files = await repo.list_for_org(org_id)
    if _wants_json(request):
        return JSONResponse([OrgFileRead.model_validate(f).model_dump(mode="json") for f in files])
    return templates.TemplateResponse(
        request, _html_template(request), _template_ctx(request, current_user, files)
    )


class RenameBody(BaseModel):
    filename: str


@router.patch("/{file_id}", response_class=HTMLResponse)
async def rename_file(
    request: Request,
    file_id: uuid.UUID,
    body: RenameBody,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    org_id: uuid.UUID = Depends(get_current_org),
    membership: Membership = Depends(get_current_membership),
):
    repo = OrgFileRepository(session)
    org_file = await repo.get(file_id, org_id)
    if org_file is None:
        return HTMLResponse("Not found", status_code=404)

    if not _can_modify(org_file.user_id, membership):
        if _wants_json(request):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        return HTMLResponse("Forbidden", status_code=403)

    await repo.rename(org_file, body.filename)

    files = await repo.list_for_org(org_id)
    if _wants_json(request):
        return JSONResponse([OrgFileRead.model_validate(f).model_dump(mode="json") for f in files])
    return templates.TemplateResponse(
        request, _html_template(request), _template_ctx(request, current_user, files)
    )


@router.post("/{file_id}/share")
async def generate_share_link(
    request: Request,
    file_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    repo = OrgFileRepository(session)
    org_file = await repo.get(file_id, org_id)
    if org_file is None:
        return JSONResponse({"detail": "Not found"}, status_code=404)

    token = await repo.add_share_token(file_id)
    return JSONResponse({"url": f"/files/share/{token.token}"})


@public_router.get("/share/{token}")
async def public_share_download(
    token: uuid.UUID,
    admin_session: AsyncSession = Depends(get_admin_session),
):
    repo = OrgFileRepository(admin_session)
    share_token = await repo.get_share_token(token)
    if share_token is None:
        return HTMLResponse("Link not found", status_code=404)
    if share_token.expires_at < datetime.now(UTC):
        return HTMLResponse("Link expired", status_code=410)

    org_file = await repo.get_by_id(share_token.file_id)
    if org_file is None:
        return HTMLResponse("File not found", status_code=404)

    storage = service_storage_client()
    result = await storage.from_(BUCKET).create_signed_url(org_file.storage_path, _SIGNED_URL_TTL)
    signed_url = result.get("signedURL") or result.get("signedUrl") or ""
    return RedirectResponse(url=signed_url, status_code=302)
