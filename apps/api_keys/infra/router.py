import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response

from apps.api_keys.contract.events import ApiKeyIssued, ApiKeyRevoked
from apps.api_keys.domain.models import ApiKeyCreated, ApiKeyRead
from apps.api_keys.domain.service import generate_key
from apps.api_keys.infra.repository import ApiKeyRepository
from apps.auth.contract.current import CurrentUser, RlsSession
from apps.organizations.contract.current import CurrentOrg, CurrentOwnerMembership
from apps.shared import clock
from apps.shared.events.bus import events
from apps.shared.http import delete_response, or_404, parse_body, wants_json
from apps.shared.http.templates import templates

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


async def _get_repo(session: RlsSession, org_id: CurrentOrg) -> ApiKeyRepository:
    return ApiKeyRepository(session, org_id)


KeyRepo = Annotated[ApiKeyRepository, Depends(_get_repo)]


async def _render(
    request: Request,
    repo: ApiKeyRepository,
    *,
    new_key: ApiKeyCreated | None = None,
) -> Response:
    """The keys panel fragment (``_keys.html``), swapped into ``#api-keys`` on the settings
    page after create/revoke. The panel's home is the org settings page — see integration."""
    keys = [ApiKeyRead.model_validate(k) for k in await repo.all()]
    ctx = {
        "keys": keys,
        "new_key": new_key,
        "org_handle": request.path_params.get("org_handle", ""),
    }
    return templates.TemplateResponse(request, "api_keys/_keys.html", ctx)


@router.get("", response_model=None)
async def list_keys(
    request: Request,
    repo: KeyRepo,
    membership: CurrentOwnerMembership,
) -> Response:
    if wants_json(request):
        keys = [ApiKeyRead.model_validate(k) for k in await repo.all()]
        return JSONResponse([k.model_dump(mode="json") for k in keys])
    # The panel lives on the org settings page; a browser hitting this URL is sent there.
    org_handle = request.path_params.get("org_handle", "")
    return RedirectResponse(f"/{org_handle}/settings", status_code=status.HTTP_303_SEE_OTHER)


@router.post("", response_model=None)
async def create_key(
    request: Request,
    current_user: CurrentUser,
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
            created_by=current_user.id,
            name=name,
            prefix=material.prefix,
            key_hash=material.key_hash,
        )
    )
    await events.emit(
        ApiKeyIssued(actor_id=current_user.id, org_id=org_id, entity_id=key.id, label=name)
    )
    created = ApiKeyCreated(secret=material.token, **ApiKeyRead.model_validate(key).model_dump())
    if wants_json(request):
        return JSONResponse(created.model_dump(mode="json"), status_code=status.HTTP_201_CREATED)
    return await _render(request, repo, new_key=created)


@router.delete("/{key_id}", response_model=None)
async def revoke_key(
    request: Request,
    key_id: uuid.UUID,
    current_user: CurrentUser,
    repo: KeyRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
) -> Response:
    key = or_404(await repo.get(key_id))
    if key.revoked_at is None:
        key.revoked_at = clock.now()
        await repo.save(key)
        await events.emit(
            ApiKeyRevoked(
                actor_id=current_user.id,
                org_id=org_id,
                entity_id=key.id,
                label=key.name,
            )
        )
    if wants_json(request):
        return delete_response(request)
    return await _render(request, repo)
