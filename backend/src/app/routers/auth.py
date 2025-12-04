"""
Authentication API router.

Provides:
- Login/logout
- Token refresh
- User registration (admin only)
- API key management
"""

import secrets
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, EmailStr

from app.auth import (
    User, Role, Permission,
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_access_token,
    generate_api_key, hash_api_key,
    get_current_user, require_permission, log_audit
)
from app.auth.oidc import get_oidc_manager
from app.database import SessionLocal
from app.models_enhanced import User as UserTable

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "viewer"
    tenant_id: Optional[str] = None


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class APIKeyResponse(BaseModel):
    api_key: str
    name: str
    created_at: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class OIDCAuthRequest(BaseModel):
    provider: str
    code: str
    code_verifier: str
    redirect_uri: Optional[str] = None


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/oidc/providers")
async def list_oidc_providers():
    """Return configured OIDC providers for the frontend."""
    manager = get_oidc_manager()
    if not manager.is_enabled():
        return []
    return await manager.list_public_configs()


@router.post("/oidc/login", response_model=LoginResponse)
async def oidc_login(request: OIDCAuthRequest, req: Request):
    """Complete OIDC code exchange and issue local JWT tokens."""
    manager = get_oidc_manager()
    if not manager.is_enabled():
        raise HTTPException(status_code=404, detail="OIDC is not configured")

    provider = manager.get_provider(request.provider)
    tokens = await provider.exchange_code(request.code, request.code_verifier, request.redirect_uri)
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=401, detail="OIDC provider did not return an ID token")

    claims = await provider.verify_id_token(id_token)
    email = claims.get("email") or claims.get("preferred_username")
    if not email:
        raise HTTPException(status_code=400, detail="OIDC token missing email claim")

    name = claims.get("name") or email
    tenant_id = claims.get(provider.config.tenant_claim) or provider.config.default_tenant
    raw_role = claims.get(provider.config.role_claim)
    if isinstance(raw_role, list):
        raw_role = raw_role[0]
    try:
        role = Role(raw_role) if raw_role else Role(provider.config.default_role)
    except ValueError:
        role = Role(provider.config.default_role)

    db = SessionLocal()
    try:
        existing = db.execute(
            UserTable.select().where(UserTable.c.email == email)
        ).fetchone()

        if existing:
            db.execute(
                UserTable.update()
                .where(UserTable.c.id == existing.id)
                .values(
                    name=name,
                    role=role.value,
                    tenant_id=tenant_id,
                    last_login=datetime.now(UTC),
                )
            )
            user_id = existing.id
        else:
            result = db.execute(UserTable.insert().values(
                email=email,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                name=name,
                role=role.value,
                tenant_id=tenant_id,
                last_login=datetime.now(UTC),
            ))
            user_id = result.lastrowid
        db.commit()

        token_payload = {
            "user_id": user_id,
            "email": email,
            "role": role.value,
            "tenant_id": tenant_id,
        }

        response = LoginResponse(
            access_token=create_access_token(token_payload),
            refresh_token=create_refresh_token(user_id),
            expires_in=86400,
            user={
                "id": user_id,
                "email": email,
                "name": name,
                "role": role.value,
                "tenant_id": tenant_id,
            },
        )

        await log_audit(
            user=User(
                id=user_id,
                email=email,
                name=name,
                role=role,
                permissions=[],
                tenant_id=tenant_id,
            ),
            action="oidc_login",
            resource_type="user",
            resource_id=user_id,
            details={"provider": provider.config.name},
            request=req,
        )

        return response
    finally:
        db.close()


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, req: Request):
    """Authenticate user and return tokens."""
    db = SessionLocal()
    
    try:
        result = db.execute(
            UserTable.select().where(UserTable.c.email == request.email)
        ).fetchone()
        
        if not result:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        if not verify_password(request.password, result.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        if not result.is_active:
            raise HTTPException(status_code=403, detail="Account is disabled")
        
        # Update last login
        db.execute(
            UserTable.update()
            .where(UserTable.c.id == result.id)
            .values(last_login=datetime.now(UTC))
        )
        db.commit()
        
        # Create tokens
        token_data = {
            "user_id": result.id,
            "email": result.email,
            "role": result.role,
            "tenant_id": result.tenant_id or "default",
        }
        
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(result.id)
        
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=86400,  # 24 hours
            user={
                "id": result.id,
                "email": result.email,
                "name": result.name,
                "role": result.role,
                "tenant_id": result.tenant_id or "default",
            }
        )
        
    finally:
        db.close()


@router.post("/refresh")
async def refresh_token(request: TokenRefreshRequest):
    """Refresh access token using refresh token."""
    try:
        payload = decode_access_token(request.refresh_token)
        
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        
        user_id = payload.get("user_id")
        
        db = SessionLocal()
        try:
            result = db.execute(
                UserTable.select().where(UserTable.c.id == user_id)
            ).fetchone()
            
            if not result or not result.is_active:
                raise HTTPException(status_code=401, detail="User not found or disabled")
            
            token_data = {
                "user_id": result.id,
                "email": result.email,
                "role": result.role,
                "tenant_id": result.tenant_id or "default",
            }
            
            return {
                "access_token": create_access_token(token_data),
                "token_type": "bearer"
            }
        finally:
            db.close()
            
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@router.post("/register")
@require_permission(Permission.USER_CREATE)
async def register_user(
    request: RegisterRequest,
    user: User = Depends(get_current_user),
    req: Request = None
):
    """Register a new user (admin only)."""
    db = SessionLocal()
    
    try:
        # Check if email exists
        existing = db.execute(
            UserTable.select().where(UserTable.c.email == request.email)
        ).fetchone()
        
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Validate role
        try:
            role = Role(request.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role: {request.role}")
        
        # Create user
        result = db.execute(UserTable.insert().values(
            email=request.email,
            password_hash=hash_password(request.password),
            name=request.name,
            role=request.role,
            tenant_id=request.tenant_id or user.tenant_id,
        ))
        db.commit()
        
        user_id = result.lastrowid
        
        # Audit log
        await log_audit(
            user=user,
            action="create",
            resource_type="user",
            resource_id=user_id,
            details={"email": request.email, "role": request.role},
            request=req
        )
        
        return {
            "id": user_id,
            "email": request.email,
            "name": request.name,
            "role": request.role,
            "tenant_id": request.tenant_id or user.tenant_id,
        }
        
    finally:
        db.close()


@router.get("/me")
async def get_current_user_info(user: User = Depends(get_current_user)):
    """Get current user information."""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "tenant_id": user.tenant_id,
        "permissions": [p.value for p in user.permissions]
    }


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    user: User = Depends(get_current_user)
):
    """Change current user's password."""
    db = SessionLocal()
    
    try:
        result = db.execute(
            UserTable.select().where(UserTable.c.id == user.id)
        ).fetchone()
        
        if not verify_password(request.current_password, result.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        
        db.execute(
            UserTable.update()
            .where(UserTable.c.id == user.id)
            .values(password_hash=hash_password(request.new_password))
        )
        db.commit()
        
        return {"message": "Password changed successfully"}
        
    finally:
        db.close()


@router.post("/api-keys", response_model=APIKeyResponse)
async def create_api_key(
    name: str = "Default API Key",
    user: User = Depends(get_current_user)
):
    """Generate a new API key for the current user."""
    db = SessionLocal()
    
    try:
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        
        db.execute(
            UserTable.update()
            .where(UserTable.c.id == user.id)
            .values(api_key=key_hash)
        )
        db.commit()
        
        return APIKeyResponse(
            api_key=api_key,
            name=name,
            created_at=datetime.now(UTC).isoformat()
        )
        
    finally:
        db.close()


@router.delete("/api-keys")
async def revoke_api_key(user: User = Depends(get_current_user)):
    """Revoke current API key."""
    db = SessionLocal()
    
    try:
        db.execute(
            UserTable.update()
            .where(UserTable.c.id == user.id)
            .values(api_key=None)
        )
        db.commit()
        
        return {"message": "API key revoked"}
        
    finally:
        db.close()


@router.get("/users")
@require_permission(Permission.USER_READ)
async def list_users(user: User = Depends(get_current_user)):
    """List all users (admin/operator only)."""
    db = SessionLocal()
    
    try:
        results = db.execute(
            UserTable.select().where(UserTable.c.tenant_id == user.tenant_id)
        ).fetchall()
        
        return [
            {
                "id": r.id,
                "email": r.email,
                "name": r.name,
                "role": r.role,
                "is_active": r.is_active,
                "tenant_id": r.tenant_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "last_login": r.last_login.isoformat() if r.last_login else None
            }
            for r in results
        ]
        
    finally:
        db.close()
