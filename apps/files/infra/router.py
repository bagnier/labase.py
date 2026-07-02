import re
import unicodedata
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from storage3.exceptions import StorageApiError

from apps.auth.contract.current import AuthenticatedUser, CurrentUser, RlsSession
from apps.files.contract import settings
from apps.files.domain.models import OrgFileRead
from apps.files.infra.repository import FileShareRepository, OrgFileRepository
from apps.files.infra.storage import (
    admin_storage,
    bucket,
    rewrite_signed_url,
    storage_path,
    user_storage_client,
)
from apps.organizations.contract.current import (
    CurrentMembership,
    CurrentOrg,
    CurrentOrgModel,
    Membership,
    OrgRole,
)
from apps.shared.clock import now
from apps.shared.http import or_404, parse_field, render_list, wants_full_page, wants_json
from apps.shared.http.templates import templates
from apps.shared.observability.audit import record_audit_event
from apps.shared.page import shell_context
from apps.shared.persistence.database import AdminSession

router = APIRouter(prefix="/files", tags=["files"])
public_router = APIRouter(prefix="/files", tags=["files"])


async def _get_file_repo(session: RlsSession, org_id: CurrentOrg) -> OrgFileRepository:
    return OrgFileRepository(session, org_id)


FileRepo = Annotated[OrgFileRepository, Depends(_get_file_repo)]

_UNSAFE_FILENAME = re.compile(r"[^a-zA-Z0-9._-]")


def _sanitize_filename(name: str) -> str:
    name = name.strip()
    if not name or ".." in name.split("/")[0] or "/" in name or "\\" in name:
        raise ValueError("Invalid filename")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    cleaned = _UNSAFE_FILENAME.sub("_", name)
    if not cleaned or cleaned.lstrip(".") == "":
        raise ValueError("Invalid filename")
    return cleaned


def _can_modify(file_user_id: uuid.UUID, membership: Membership) -> bool:
    return file_user_id == membership.auth_user_id or membership.role == OrgRole.owner


async def _render(
    request: Request,
    session: RlsSession,
    current_user: AuthenticatedUser,
    files: list,
    org,
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
        extra={
            "welcome_message": settings.welcome_message,
            "uploads_enabled": settings.uploads_enabled,
            "storage_quota_mb": settings.org_storage_quota_mb,
            "used_bytes": sum(f.size_bytes for f in files),
        },
    )


@router.get("", response_class=HTMLResponse)
async def file_list(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org: CurrentOrgModel,
    repo: FileRepo,
):
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
    repo: FileRepo,
):
    if not settings.uploads_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Uploads are disabled")

    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        return HTMLResponse(
            '<div role="alert" class="alert-error">File too large</div>',
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    quota_mb = settings.org_storage_quota_mb
    if quota_mb >= 0 and await repo.total_size() + len(content) > quota_mb * 1024 * 1024:
        return HTMLResponse(
            '<div role="alert" class="alert-error">Organisation storage quota exceeded</div>',
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    try:
        safe_name = _sanitize_filename(file.filename or "upload")
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename") from None

    file_id = uuid.uuid4()
    path = storage_path(org_id, file_id, safe_name)
    content_type = file.content_type or "application/octet-stream"

    storage = user_storage_client(current_user.access_token)
    try:
        await storage.from_(bucket()).upload(path, content, {"content-type": content_type})
    except StorageApiError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

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
    repo: FileRepo,
):
    org_file = or_404(await repo.get(file_id))
    storage = user_storage_client(current_user.access_token)
    result = await storage.from_(bucket()).create_signed_url(
        org_file.storage_path, settings.signed_url_ttl
    )
    signed_url = rewrite_signed_url(result.get("signedURL") or result.get("signedUrl") or "")
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
    repo: FileRepo,
):
    org_file = or_404(await repo.get(file_id))
    if not _can_modify(org_file.user_id, membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")

    storage = user_storage_client(current_user.access_token)
    await storage.from_(bucket()).remove([org_file.storage_path])
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


@router.patch("/{file_id}", response_class=HTMLResponse)
async def rename_file(
    request: Request,
    bg: BackgroundTasks,
    file_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
    membership: CurrentMembership,
    repo: FileRepo,
):
    filename = await parse_field(request, "filename")

    try:
        safe_name = _sanitize_filename(filename)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename") from None

    org_file = or_404(await repo.get(file_id))
    if not _can_modify(org_file.user_id, membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")

    new_path = storage_path(org_id, file_id, safe_name)
    storage = user_storage_client(current_user.access_token)
    try:
        await storage.from_(bucket()).move(org_file.storage_path, new_path)
    except StorageApiError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    old_filename = org_file.filename
    await repo.rename(org_file, safe_name, new_path)
    record_audit_event(
        bg,
        level="info",
        event="file.renamed",
        user_id=current_user.id,
        org_id=str(org_id),
        file_id=str(file_id),
        old_filename=old_filename,
        new_filename=safe_name,
    )

    files = await repo.all()
    return await _render(request, session, current_user, files, org)


@router.post("/{file_id}/share")
async def generate_share_link(
    request: Request,
    bg: BackgroundTasks,
    file_id: uuid.UUID,
    current_user: CurrentUser,
    org_id: CurrentOrg,
    repo: FileRepo,
):
    org_file = or_404(await repo.get(file_id))
    token = await repo.add_share_token(file_id)
    record_audit_event(
        bg,
        level="info",
        event="file.share_link_created",
        user_id=current_user.id,
        org_id=str(org_id),
        file_id=str(file_id),
        token=str(token.token),
    )
    url = str(request.base_url) + f"files/share/{token.token}"
    if wants_json(request):
        return JSONResponse({"url": url})
    return templates.TemplateResponse(
        request,
        "files/_share_result.html",
        {"url": url, "filename": org_file.filename},
    )


@public_router.get("/share/{token}")
async def public_share_download(
    request: Request,
    bg: BackgroundTasks,
    token: uuid.UUID,
    admin_session: AdminSession,
):
    ip = request.client.host if request.client else None
    repo = FileShareRepository(admin_session)
    share_token = await repo.get_share_token(token)
    if share_token is None:
        record_audit_event(
            bg,
            level="warning",
            event="file.share_link_rejected",
            ip=ip,
            token=str(token),
            reason="invalid",
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    if share_token.expires_at < now():
        record_audit_event(
            bg,
            level="warning",
            event="file.share_link_rejected",
            ip=ip,
            token=str(token),
            reason="expired",
        )
        raise HTTPException(status.HTTP_410_GONE, "Link expired")

    org_file = await repo.get(share_token.file_id)
    if org_file is None:
        record_audit_event(
            bg,
            level="warning",
            event="file.share_link_rejected",
            ip=ip,
            token=str(token),
            reason="file_missing",
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")

    record_audit_event(
        bg,
        level="info",
        event="file.share_downloaded",
        org_id=str(org_file.org_id),
        file_id=str(org_file.id),
        token=str(token),
        ip=ip,
    )
    storage = admin_storage()
    result = await storage.from_(bucket()).create_signed_url(
        org_file.storage_path, settings.signed_url_ttl
    )
    signed_url = rewrite_signed_url(result.get("signedURL") or result.get("signedUrl") or "")
    return RedirectResponse(url=signed_url, status_code=302)
