import uuid

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.files.domain.models import OrgFileRead
from app.files.infra.repository import OrgFileRepository
from app.files.infra.storage import BUCKET, service_storage_client, storage_path
from app.organizations.infra.context import get_current_org
from app.shared.database import get_session
from app.shared.templates import templates

router = APIRouter(prefix="/files", tags=["files"])

_SIGNED_URL_TTL = 60


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _html_template(request: Request) -> str:
    return "files/_list_fragment.html" if _is_htmx(request) else "files/list.html"


@router.get("", response_class=HTMLResponse)
async def file_list(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    repo = OrgFileRepository(session)
    files = await repo.list_for_org(org_id)
    if _wants_json(request):
        return JSONResponse([OrgFileRead.model_validate(f).model_dump(mode="json") for f in files])
    return templates.TemplateResponse(
        request, _html_template(request), {"user": current_user, "files": files}
    )


@router.post("", response_class=HTMLResponse)
async def upload_file(
    request: Request,
    file: UploadFile,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    content = await file.read()
    file_id = uuid.uuid4()
    path = storage_path(org_id, file_id, file.filename or "upload")
    content_type = file.content_type or "application/octet-stream"

    storage = service_storage_client()
    await storage.from_(BUCKET).upload(path, content, {"content-type": content_type})

    repo = OrgFileRepository(session)
    await repo.add(
        org_id=org_id,
        user_id=uuid.UUID(current_user.id),
        filename=file.filename or "upload",
        storage_path=path,
        content_type=content_type,
        size_bytes=len(content),
    )

    files = await repo.list_for_org(org_id)
    if _wants_json(request):
        return JSONResponse([OrgFileRead.model_validate(f).model_dump(mode="json") for f in files])
    return templates.TemplateResponse(
        request, _html_template(request), {"user": current_user, "files": files}
    )


@router.get("/{file_id}/download")
async def download_file(
    file_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    repo = OrgFileRepository(session)
    org_file = await repo.get(file_id, org_id)
    if org_file is None:
        return HTMLResponse("Not found", status_code=404)

    storage = service_storage_client()
    result = await storage.from_(BUCKET).create_signed_url(org_file.storage_path, _SIGNED_URL_TTL)
    signed_url = result.get("signedURL") or result.get("signedUrl") or ""
    return RedirectResponse(url=signed_url, status_code=302)


@router.delete("/{file_id}", response_class=HTMLResponse)
async def delete_file(
    request: Request,
    file_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org),
):
    repo = OrgFileRepository(session)
    org_file = await repo.get(file_id, org_id)
    if org_file:
        storage = service_storage_client()
        await storage.from_(BUCKET).remove([org_file.storage_path])
        await repo.delete(org_file)

    files = await repo.list_for_org(org_id)
    if _wants_json(request):
        return JSONResponse([OrgFileRead.model_validate(f).model_dump(mode="json") for f in files])
    return templates.TemplateResponse(
        request, _html_template(request), {"user": current_user, "files": files}
    )
