import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from storage3.exceptions import StorageApiError

from app.auth.domain.service import AuthenticatedUser
from app.files.domain.models import OrgFileRead
from app.files.infra.repository import FileShareRepository, OrgFileRepository
from app.files.infra.storage import (
    BUCKET,
    service_storage_client,
    storage_path,
    user_storage_client,
)
from app.organizations.domain.models import Membership, Organization, OrgRole
from app.profile.infra.shell import shell_context
from app.shared.dependencies import (
    AdminSession,
    CurrentMembership,
    CurrentOrg,
    CurrentOrgModel,
    CurrentUser,
    RlsSession,
)
from app.shared.http import render_list, wants_full_page
from app.shared.observability.audit import record_audit_event

router = APIRouter(prefix="/files", tags=["files"])
public_router = APIRouter(prefix="/files", tags=["files"])

_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_filename(name: str) -> str:
    name = name.strip()
    if not name or ".." in name.split("/")[0] or "/" in name or "\\" in name:
        raise ValueError("Invalid filename")
    cleaned = _UNSAFE_FILENAME.sub("_", name)
    if not cleaned or cleaned.lstrip(".") == "":
        raise ValueError("Invalid filename")
    return cleaned


_MAX_SIZE_BYTES = 50 * 1024 * 1024
_SIGNED_URL_TTL = 60


def _can_modify(file_user_id: uuid.UUID, membership: Membership) -> bool:
    return file_user_id == membership.auth_user_id or membership.role == OrgRole.owner


async def _render(
    request: Request,
    session: RlsSession,
    current_user: AuthenticatedUser,
    files: list,
    org: Organization,
) -> Response:
    shell = await shell_context(session, current_user) if wants_full_page(request) else None
    return render_list(
        request,
        fragment="files/_list_fragment.html",
        full="files/files.html",
        items_key="files",
        schema=OrgFileRead,
        items=files,
        user=current_user,
        org=org,
        shell=shell,
    )


@router.get("", response_class=HTMLResponse)
async def file_list(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
):
    repo = OrgFileRepository(session, org_id)
    files = await repo.all()
    return await _render(request, session, current_user, files, org)


@router.post("", response_class=HTMLResponse)
async def upload_file(
    request: Request,
    bg: BackgroundTasks,
    file: UploadFile,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
):
    content = await file.read()
    if len(content) > _MAX_SIZE_BYTES:
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"detail": "File too large"}, status_code=413)
        return HTMLResponse("File too large", status_code=413)

    try:
        safe_name = _sanitize_filename(file.filename or "upload")
    except ValueError:
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"detail": "Invalid filename"}, status_code=400)
        return HTMLResponse("Invalid filename", status_code=400)

    file_id = uuid.uuid4()
    path = storage_path(org_id, file_id, safe_name)
    content_type = file.content_type or "application/octet-stream"

    storage = user_storage_client(current_user.access_token)
    try:
        await storage.from_(BUCKET).upload(path, content, {"content-type": content_type})
    except StorageApiError as exc:
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return HTMLResponse(f"Upload rejected: {exc}", status_code=400)

    repo = OrgFileRepository(session, org_id)
    org_file = await repo.add(
        user_id=uuid.UUID(current_user.id),
        filename=safe_name,
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

    files = await repo.all()
    return await _render(request, session, current_user, files, org)


@router.get("/{file_id}/download")
async def download_file(
    file_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
):
    repo = OrgFileRepository(session, org_id)
    org_file = await repo.get(file_id)
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
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
    membership: CurrentMembership,
):
    repo = OrgFileRepository(session, org_id)
    org_file = await repo.get(file_id)
    if org_file is None:
        return HTMLResponse("Not found", status_code=404)

    if not _can_modify(org_file.user_id, membership):
        if "application/json" in request.headers.get("accept", ""):
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

    files = await repo.all()
    return await _render(request, session, current_user, files, org)


class RenameBody(BaseModel):
    filename: str


@router.patch("/{file_id}", response_class=HTMLResponse)
async def rename_file(
    request: Request,
    file_id: uuid.UUID,
    body: RenameBody,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
    membership: CurrentMembership,
):
    repo = OrgFileRepository(session, org_id)
    org_file = await repo.get(file_id)
    if org_file is None:
        return HTMLResponse("Not found", status_code=404)

    if not _can_modify(org_file.user_id, membership):
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        return HTMLResponse("Forbidden", status_code=403)

    await repo.rename(org_file, body.filename)

    files = await repo.all()
    return await _render(request, session, current_user, files, org)


@router.post("/{file_id}/share")
async def generate_share_link(
    request: Request,
    file_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
):
    repo = OrgFileRepository(session, org_id)
    org_file = await repo.get(file_id)
    if org_file is None:
        return JSONResponse({"detail": "Not found"}, status_code=404)

    token = await repo.add_share_token(file_id)
    return JSONResponse({"url": f"/files/share/{token.token}"})


@public_router.get("/share/{token}")
async def public_share_download(
    token: uuid.UUID,
    admin_session: AdminSession,
):
    repo = FileShareRepository(admin_session)
    share_token = await repo.get_share_token(token)
    if share_token is None:
        return HTMLResponse("Link not found", status_code=404)
    if share_token.expires_at < datetime.now(UTC):
        return HTMLResponse("Link expired", status_code=410)

    org_file = await repo.get(share_token.file_id)
    if org_file is None:
        return HTMLResponse("File not found", status_code=404)

    storage = service_storage_client()
    result = await storage.from_(BUCKET).create_signed_url(org_file.storage_path, _SIGNED_URL_TTL)
    signed_url = result.get("signedURL") or result.get("signedUrl") or ""
    return RedirectResponse(url=signed_url, status_code=302)
