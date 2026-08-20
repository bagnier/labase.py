import re
import unicodedata
import uuid
from typing import Annotated, NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from storage3.exceptions import StorageApiError

from apps.auth.contract.current import AuthenticatedUser, CurrentUser, RlsSession
from apps.files.contract.current import FilesSettings
from apps.files.contract.events import (
    FileDeleted,
    FileRenamed,
    FileShareDownloaded,
    FileShareLinkCreated,
    FileUploaded,
)
from apps.files.domain.models import OrgFileRead
from apps.files.infra.repository import FileShareRepository, OrgFileRepository
from apps.files.infra.storage import signed_redirect_url, storage_path
from apps.organizations.contract.current import (
    CurrentMembership,
    CurrentOrg,
    CurrentOrgModel,
    Membership,
    OrgRole,
)
from apps.shared.clock import now
from apps.shared.events.bus import events
from apps.shared.http import (
    delete_response,
    or_404,
    parse_field,
    render_list,
    wants_full_page,
    wants_json,
)
from apps.shared.http.templates import templates
from apps.shared.logs.dependency import is_refusal, log_dependency_failure
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession
from apps.shared.persistence.storage import admin_storage, bucket, user_storage_client
from apps.shared.settings import SettingsView, get_settings

log = structlog.get_logger(__name__)


def storage_failure(event: str, exc: StorageApiError, **context: object) -> HTTPException:
    """One verdict for a failed Storage call, and the answer the caller is owed.

    Storage is a dependency like GoTrue or Postgres, so the level is the base's
    (:mod:`apps.shared.logs.dependency`) — a 4xx is Storage answering no (a name already
    taken, an object that isn't there), anything else is Storage being broken, which the capture
    seam tracks as an issue. Logged with *this* module's logger, so the issue and the lines around
    it file under ``files`` rather than under ``shared``.

    The status follows the same split: only a refusal is the caller's fault. Answering 400 to an
    outage told a user their upload was malformed when it was fine, and hid the outage behind a
    status nothing alerts on.
    """
    log_dependency_failure(log, event, exc, **context)
    if is_refusal(exc):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Storage is unavailable")


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


def _can_modify(uploaded_by: uuid.UUID, membership: Membership) -> bool:
    return uploaded_by == membership.user_id or membership.role == OrgRole.owner


async def _render(
    request: Request,
    session: RlsSession,
    current_user: AuthenticatedUser,
    files: list,
    org,
    settings: SettingsView,
) -> Response:
    context = await fullpage_context(session, current_user) if wants_full_page(request) else None
    return render_list(
        request,
        fragment="files/_list_fragment.html",
        full="files/files.html",
        items_key="files",
        schema=OrgFileRead,
        items=files,
        user=current_user,
        org=org,
        context=context,
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
    settings: FilesSettings,
):
    files = await repo.all()
    return await _render(request, session, current_user, files, org, settings)


@router.post("", response_class=HTMLResponse)
async def upload_file(
    request: Request,
    file: UploadFile,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
    repo: FileRepo,
    settings: FilesSettings,
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

    file_id = uuid.uuid7()
    path = storage_path(org_id, file_id, safe_name)
    content_type = file.content_type or "application/octet-stream"

    storage = user_storage_client(current_user.access_token)
    try:
        await storage.from_(bucket()).upload(path, content, {"content-type": content_type})
    except StorageApiError as exc:
        raise storage_failure("files.upload_failed", exc, path=path) from exc

    org_file = await repo.add(
        uploaded_by=current_user.id,
        filename=safe_name,
        storage_path=path,
        content_type=content_type,
        size_bytes=len(content),
        uploader_email=current_user.email,
    )
    await events.emit(
        FileUploaded(
            user_id=current_user.id,
            org_id=org_id,
            entity_id=org_file.id,
            entity_name=org_file.filename,
        ),
        session,
    )

    if wants_json(request):
        # Lets other surfaces (e.g. the pages editor's image upload) get a usable
        # reference back instead of the files-list HTML fragment.
        return JSONResponse(
            {
                "id": str(org_file.id),
                "filename": org_file.filename,
                "content_type": org_file.content_type,
                "url": f"/{org.handle}/files/{org_file.id}/download",
            },
            status_code=status.HTTP_201_CREATED,
        )
    files = await repo.all()
    return await _render(request, session, current_user, files, org, settings)


@router.get("/{file_id}/download")
async def download_file(
    file_id: uuid.UUID,
    current_user: CurrentUser,
    repo: FileRepo,
    settings: FilesSettings,
):
    org_file = or_404(await repo.get(file_id))
    storage = user_storage_client(current_user.access_token)
    result = await storage.from_(bucket()).create_signed_url(
        org_file.storage_path, settings.signed_url_ttl
    )
    return RedirectResponse(url=signed_redirect_url(result), status_code=302)


@router.delete("/{file_id}", response_class=HTMLResponse)
async def delete_file(
    request: Request,
    file_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
    membership: CurrentMembership,
    repo: FileRepo,
    settings: FilesSettings,
):
    org_file = or_404(await repo.get(file_id))
    if not _can_modify(org_file.uploaded_by, membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")

    storage = user_storage_client(current_user.access_token)
    await storage.from_(bucket()).remove([org_file.storage_path])
    await repo.delete(org_file)
    await events.emit(
        FileDeleted(
            user_id=current_user.id,
            org_id=org_id,
            entity_id=file_id,
            entity_name=org_file.filename,
        ),
        session,
    )

    if wants_json(request):
        return delete_response(request)
    files = await repo.all()
    return await _render(request, session, current_user, files, org, settings)


@router.patch("/{file_id}", response_class=HTMLResponse)
async def rename_file(
    request: Request,
    file_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
    membership: CurrentMembership,
    repo: FileRepo,
    settings: FilesSettings,
):
    filename = await parse_field(request, "filename")

    try:
        safe_name = _sanitize_filename(filename)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename") from None

    org_file = or_404(await repo.get(file_id))
    if not _can_modify(org_file.uploaded_by, membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")

    new_path = storage_path(org_id, file_id, safe_name)
    storage = user_storage_client(current_user.access_token)
    try:
        await storage.from_(bucket()).move(org_file.storage_path, new_path)
    except StorageApiError as exc:
        raise storage_failure("files.rename_failed", exc, path=new_path) from exc

    old_filename = org_file.filename
    await repo.rename(org_file, safe_name, new_path)
    await events.emit(
        FileRenamed(
            user_id=current_user.id,
            org_id=org_id,
            entity_id=file_id,
            entity_name=safe_name,
            old_filename=old_filename,
        ),
        session,
    )

    files = await repo.all()
    return await _render(request, session, current_user, files, org, settings)


@router.post("/{file_id}/share")
async def generate_share_link(
    request: Request,
    file_id: uuid.UUID,
    current_user: CurrentUser,
    org_id: CurrentOrg,
    repo: FileRepo,
):
    org_file = or_404(await repo.get(file_id))
    token = await repo.add_share_token(file_id)
    await events.emit(
        FileShareLinkCreated(
            user_id=current_user.id,
            org_id=org_id,
            entity_id=file_id,
        ),
        repo.session,
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
    token: uuid.UUID,
    admin_session: AdminSession,
):
    async def reject(reason: str, code: int, detail: str) -> NoReturn:
        # Anonymous attempt: no actor, no org — a refusal, not a fact.
        log.warning("files.share_link_rejected", reason=reason, token=str(token))
        raise HTTPException(code, detail)

    repo = FileShareRepository(admin_session)
    share_token = await repo.get_share_token(token)
    if share_token is None:
        await reject("invalid", status.HTTP_404_NOT_FOUND, "Link not found")
    if share_token.expires_at < now():
        await reject("expired", status.HTTP_410_GONE, "Link expired")

    org_file = await repo.get(share_token.file_id)
    if org_file is None:
        await reject("file_missing", status.HTTP_404_NOT_FOUND, "File not found")

    await events.emit(
        FileShareDownloaded(org_id=org_file.org_id, entity_id=org_file.id), admin_session
    )
    # Effective TTL for the file's org — the admin session reads its overrides (no RLS caller
    # here: share downloads are anonymous, the org comes from the file row).
    effective = await get_settings("files").for_org(admin_session, org_file.org_id)
    storage = admin_storage()
    result = await storage.from_(bucket()).create_signed_url(
        org_file.storage_path, effective.signed_url_ttl
    )
    return RedirectResponse(url=signed_redirect_url(result), status_code=302)
