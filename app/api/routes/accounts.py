"""Administrator account-management routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_auth_service, require_admin_context
from app.api.models import (
    AccountListResponse,
    AdminUserResponse,
    CreateAccountRequest,
    DeleteAccountRequest,
    IdDeleteResponse,
    ResetPasswordRequest,
    UpdateAccountRequest,
)

router = APIRouter(
    prefix="/api/v1/accounts",
    tags=["accounts"],
    dependencies=[Depends(require_admin_context)],
)


@router.get("", response_model=AccountListResponse)
async def list_accounts():
    """List ordinary accounts."""
    accounts = get_auth_service().list_accounts()
    return AccountListResponse(accounts=[AdminUserResponse(**item) for item in accounts])


@router.post("", response_model=AdminUserResponse, status_code=201)
async def create_account(req: CreateAccountRequest):
    """Create an ordinary account."""
    try:
        account = get_auth_service().create_user_account(
            req.username,
            req.password,
            enabled=req.enabled,
        )
    except ValueError as exc:
        status = 409 if str(exc) == "Username already exists" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return AdminUserResponse(**account)


@router.patch("/{account_id}", response_model=AdminUserResponse)
async def update_account(account_id: str, req: UpdateAccountRequest):
    """Enable or disable an ordinary account."""
    try:
        account = get_auth_service().set_account_enabled(account_id, req.enabled)
    except ValueError as exc:
        status = 404 if str(exc) == "Account not found" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return AdminUserResponse(**account)


@router.post("/{account_id}/reset-password", response_model=IdDeleteResponse)
async def reset_password(account_id: str, req: ResetPasswordRequest):
    """Reset an ordinary account password."""
    try:
        get_auth_service().reset_password(account_id, req.new_password)
    except ValueError as exc:
        status = 404 if str(exc) == "Account not found" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return IdDeleteResponse(deleted=False, id=account_id)


@router.delete("/{account_id}", response_model=IdDeleteResponse)
async def delete_account(account_id: str, req: DeleteAccountRequest):
    """Delete an ordinary account after exact username confirmation."""
    service = get_auth_service()
    try:
        account = service.get_account(account_id)
        if req.confirm_username != account["username"]:
            raise HTTPException(status_code=400, detail="Username confirmation does not match")
        service.delete_account(account_id)
    except ValueError as exc:
        status = 404 if str(exc) == "Account not found" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return IdDeleteResponse(deleted=True, id=account_id)
