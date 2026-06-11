"""API key management routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_auth_service, require_admin_context
from app.api.models import (
    ApiKeyCreateResponse,
    ApiKeyListResponse,
    ApiKeyResponse,
    CreateApiKeyRequest,
    IdDeleteResponse,
    UpdateApiKeyRequest,
)

router = APIRouter(
    prefix="/api/v1/api-keys",
    tags=["api-keys"],
    dependencies=[Depends(require_admin_context)],
)


@router.get("", response_model=ApiKeyListResponse)
async def list_api_keys():
    """List external API clients."""
    keys = get_auth_service().list_api_keys()
    return ApiKeyListResponse(api_keys=[ApiKeyResponse(**key) for key in keys])


@router.post("", response_model=ApiKeyCreateResponse, status_code=201)
async def create_api_key(req: CreateApiKeyRequest):
    """Create a new API key and return the secret once."""
    try:
        key, secret = get_auth_service().create_api_key(req.name, req.scope, req.instance_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ApiKeyCreateResponse(api_key=ApiKeyResponse(**key), secret=secret)


@router.patch("/{client_id}", response_model=ApiKeyResponse)
async def update_api_key(client_id: str, req: UpdateApiKeyRequest):
    """Update API key metadata, scope, enabled state, or instance grants."""
    try:
        key = get_auth_service().update_api_key(
            client_id,
            name=req.name,
            scope=req.scope,
            enabled=req.enabled,
            instance_ids=req.instance_ids,
        )
    except ValueError as e:
        status = 404 if str(e) == "API key not found" else 400
        raise HTTPException(status_code=status, detail=str(e)) from e
    return ApiKeyResponse(**key)


@router.delete("/{client_id}", response_model=IdDeleteResponse)
async def delete_api_key(client_id: str):
    """Delete an API key."""
    try:
        get_auth_service().delete_api_key(client_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return IdDeleteResponse(deleted=True, id=client_id)


@router.post("/{client_id}/rotate", response_model=ApiKeyCreateResponse)
async def rotate_api_key(client_id: str):
    """Rotate an API key and return the new secret once."""
    try:
        key, secret = get_auth_service().rotate_api_key(client_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ApiKeyCreateResponse(api_key=ApiKeyResponse(**key), secret=secret)
