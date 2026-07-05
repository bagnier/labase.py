import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.responses import JSONResponse, Response

from apps.api_keys.domain.models import ApiKeyCreated, ApiKeyRead
from apps.api_keys.domain.service import generate_key
from apps.api_keys.infra.repository import ApiKeyRepository
from apps.auth.contract.current import CurrentUser, RlsSession
from apps.organizations.contract.current import (
    CurrentOrg,
    CurrentOrgModel,
    CurrentOwnerMembership,
)
from apps.shared import clock
from apps.shared.http import delete_response, or_404, parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.observability.audit import audit
from apps.shared.page import fullpage_context

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


async def _get_repo(session: RlsSession, org_id: CurrentOrg) -> ApiKeyRepository:
    return ApiKeyRepository(session, org_id)


KeyRepo = Annotated[ApiKeyRepository, Depends(_get_repo)]


async def _render(
    request: Request,
    session,
    current_user,
    repo: ApiKeyRepository,
    org,
    *,
    new_key: ApiKeyCreated | None = None,
    full_page: bool = False,
) -> Response:
    keys = [ApiKeyRead.model_validate(k) for k in await repo.all()]
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "api_keys/index.html" if (full_page and not is_htmx) else "api_keys/_keys.html"
    ctx = {
        "user": current_user,
        "keys": keys,
        "new_key": new_key,
        "org_handle": request.path_params.get("org_handle", ""),
        "org": org,
    }
    if template.endswith("index.html"):
        ctx |= await fullpage_context(session, current_user)
    return templates.TemplateResponse(request, template, ctx)


@router.get("", response_model=None)
async def list_keys(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: KeyRepo,
    org: CurrentOrgModel,
    membership: CurrentOwnerMembership,
) -> Response:
    if wants_json(request):
        keys = [ApiKeyRead.model_validate(k) for k in await repo.all()]
        return JSONResponse([k.model_dump(mode="json") for k in keys])
    return await _render(request, session, current_user, repo, org, full_page=True)


@router.post("", response_model=None)
async def create_key(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    session: RlsSession,
    repo: KeyRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
) -> Response:
    body = await parse_body(request)
    name = str(body.get("name", "")).strip() or "unnamed key"
    material = generate_key()
    key = await repo.save(
        repo.model(
            org_id=org_id,
            created_by=uuid.UUID(current_user.id),
            name=name,
            prefix=material.prefix,
            key_hash=material.key_hash,
        )
    )
    audit(
        bg,
        "api_keys.created",
        user_id=current_user.id,
        org_id=org_id,
        key_id=str(key.id),
        name=name,
    )
    created = ApiKeyCreated(secret=material.token, **ApiKeyRead.model_validate(key).model_dump())
    if wants_json(request):
        return JSONResponse(created.model_dump(mode="json"), status_code=status.HTTP_201_CREATED)
    return await _render(request, session, current_user, repo, None, new_key=created)


@router.delete("/{key_id}", response_model=None)
async def revoke_key(
    request: Request,
    bg: BackgroundTasks,
    key_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: KeyRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
) -> Response:
    key = or_404(await repo.get(key_id))
    if key.revoked_at is None:
        key.revoked_at = clock.now()
        await repo.save(key)
        audit(
            bg,
            "api_keys.revoked",
            user_id=current_user.id,
            org_id=org_id,
            key_id=str(key.id),
            name=key.name,
        )
    if wants_json(request):
        return delete_response(request)
    return await _render(request, session, current_user, repo, None)
