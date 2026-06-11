"""Authentication routes for the management console."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.dependencies import AUTH_COOKIE_NAME, get_auth_service, get_optional_auth_context, require_admin_context
from app.api.models import (
    AdminSetupRequest,
    AdminUserResponse,
    AuthResponse,
    AuthStatusResponse,
    LoginRequest,
    LogoutResponse,
)
from app.config import get_settings
from app.security.request_guards import should_use_secure_cookie

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(request: Request):
    """Return setup and login state for the console gate."""
    svc = get_auth_service()
    context = await get_optional_auth_context(request)
    user = None
    if context and context.is_admin:
        user = AdminUserResponse(id=context.user_id or "", username=context.username or "")
    return AuthStatusResponse(
        setup_required=not svc.has_admin(),
        authenticated=bool(user),
        user=user,
    )


@router.post("/setup", response_model=AuthResponse)
async def setup_admin(req: AdminSetupRequest, response: Response, request: Request):
    """Create the initial administrator account and open a console session."""
    svc = get_auth_service()
    try:
        user = svc.setup_admin(req.username, req.password)
        token, expires_at = svc.create_session(user["id"])
    except ValueError as e:
        status = 409 if str(e) == "Admin setup already completed" else 400
        raise HTTPException(status_code=status, detail=str(e)) from e

    _set_session_cookie(response, request, token, expires_at)
    return AuthResponse(user=AdminUserResponse(**user))


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, response: Response, request: Request):
    """Login to the management console."""
    svc = get_auth_service()
    if not svc.has_admin():
        raise HTTPException(status_code=403, detail="Admin setup required")

    user = svc.verify_admin(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token, expires_at = svc.create_session(user["id"])
    _set_session_cookie(response, request, token, expires_at)
    return AuthResponse(user=AdminUserResponse(**user))


@router.post("/logout", response_model=LogoutResponse)
async def logout(request: Request, response: Response):
    """Logout the current administrator session."""
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if token:
        get_auth_service().delete_session(token)
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", samesite="lax")
    return LogoutResponse()


@router.get("/me", response_model=AuthResponse)
async def me(context=Depends(require_admin_context)):
    """Return the current administrator."""
    return AuthResponse(
        user=AdminUserResponse(id=context.user_id or "", username=context.username or "")
    )


def _set_session_cookie(response: Response, request: Request, token: str, expires_at: str) -> None:
    del expires_at
    settings = get_settings()
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=should_use_secure_cookie(request, settings),
        samesite="lax",
        path="/",
    )
