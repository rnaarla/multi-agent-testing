"""
Authentication and Role-Based Access Control (RBAC) system.

Provides:
- JWT-based authentication
- API key authentication
- Role-based permissions
- Session management
"""

import json
import os
import secrets
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
from functools import wraps

from fastapi import HTTPException, Depends, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader

from app.services.secrets import get_secret
from app.utils.request_context import get_correlation_id


# ============================================================================
# Configuration
# ============================================================================

JWT_SECRET = get_secret("auth/jwt_secret", os.getenv("JWT_SECRET")) or secrets.token_hex(32)
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))
API_KEY_PREFIX = "mat_"  # Multi-Agent Testing
AUDIT_RETENTION_DAYS = int(os.getenv("AUDIT_LOG_RETENTION_DAYS", "365"))


# ============================================================================
# Roles and Permissions
# ============================================================================

class Role(Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    API = "api"


class Permission(Enum):
    # Graph permissions
    GRAPH_CREATE = "graph:create"
    GRAPH_READ = "graph:read"
    GRAPH_UPDATE = "graph:update"
    GRAPH_DELETE = "graph:delete"
    GRAPH_LIBRARY = "graph:library"
    
    # Run permissions
    RUN_CREATE = "run:create"
    RUN_READ = "run:read"
    RUN_CANCEL = "run:cancel"
    
    # Metrics permissions
    METRICS_READ = "metrics:read"
    METRICS_EXPORT = "metrics:export"
    
    # User management
    USER_CREATE = "user:create"
    USER_READ = "user:read"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    
    # System permissions
    SYSTEM_CONFIG = "system:config"
    AUDIT_READ = "audit:read"
    WEBHOOK_MANAGE = "webhook:manage"


# Role-permission mapping
ROLE_PERMISSIONS: Dict[Role, List[Permission]] = {
    Role.ADMIN: list(Permission),  # All permissions
    
    Role.OPERATOR: [
        Permission.GRAPH_CREATE,
        Permission.GRAPH_READ,
        Permission.GRAPH_UPDATE,
        Permission.GRAPH_LIBRARY,
        Permission.RUN_CREATE,
        Permission.RUN_READ,
        Permission.RUN_CANCEL,
        Permission.METRICS_READ,
        Permission.METRICS_EXPORT,
        Permission.USER_READ,
        Permission.WEBHOOK_MANAGE,
    ],
    
    Role.VIEWER: [
        Permission.GRAPH_READ,
        Permission.GRAPH_LIBRARY,
        Permission.RUN_READ,
        Permission.METRICS_READ,
    ],
    
    Role.API: [
        Permission.GRAPH_READ,
        Permission.RUN_CREATE,
        Permission.RUN_READ,
        Permission.METRICS_READ,
    ],
}


# ============================================================================
# User Model
# ============================================================================

@dataclass
class User:
    """Authenticated user context."""
    id: int
    email: str
    name: str
    role: Role
    permissions: List[Permission]
    api_key: Optional[str] = None
    is_active: bool = True
    tenant_id: str = "default"
    
    def has_permission(self, permission: Permission) -> bool:
        """Check if user has a specific permission."""
        return permission in self.permissions
    
    def has_any_permission(self, permissions: List[Permission]) -> bool:
        """Check if user has any of the specified permissions."""
        return any(p in self.permissions for p in permissions)
    
    def has_all_permissions(self, permissions: List[Permission]) -> bool:
        """Check if user has all of the specified permissions."""
        return all(p in self.permissions for p in permissions)


# ============================================================================
# Password Hashing
# ============================================================================

def hash_password(password: str) -> str:
    """Hash a password with salt."""
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        100000
    )
    return f"{salt}${hash_obj.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    try:
        salt, stored_hash = password_hash.split("$")
        hash_obj = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt.encode(),
            100000
        )
        return secrets.compare_digest(hash_obj.hex(), stored_hash)
    except (ValueError, AttributeError):
        return False


# ============================================================================
# JWT Token Management
# ============================================================================

def create_access_token(user_data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    try:
        import jwt
    except ImportError:
        # Fallback: simple base64 token if jwt not available
        import base64
        import json

        data = {**user_data, "exp": (datetime.now(UTC) + timedelta(hours=JWT_EXPIRY_HOURS)).isoformat()}
        return base64.b64encode(json.dumps(data).encode()).decode()
    
    expire = datetime.now(UTC) + (expires_delta or timedelta(hours=JWT_EXPIRY_HOURS))
    
    payload = {
        **user_data,
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "access"
    }
    
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT token."""
    try:
        import jwt
    except ImportError:
        import base64
        import json
        try:
            data = json.loads(base64.b64decode(token).decode())
            if datetime.fromisoformat(data["exp"]) < datetime.now(UTC):
                raise HTTPException(status_code=401, detail="Token expired")
            return data
        except:
            raise HTTPException(status_code=401, detail="Invalid token")
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def create_refresh_token(user_id: int) -> str:
    """Create a refresh token."""
    try:
        import jwt
        
        expire = datetime.now(UTC) + timedelta(days=30)
        payload = {
            "user_id": user_id,
            "exp": expire,
            "type": "refresh"
        }
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    except ImportError:
        return secrets.token_urlsafe(32)


# ============================================================================
# API Key Management
# ============================================================================

def generate_api_key() -> str:
    """Generate a new API key."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage."""
    return hashlib.sha256(api_key.encode()).hexdigest()


# ============================================================================
# FastAPI Dependencies
# ============================================================================

security = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    api_key: Optional[str] = Depends(api_key_header),
    request: Request = None
) -> User:
    """
    Extract and validate the current user from request.
    
    Supports:
    - Bearer JWT token
    - X-API-Key header
    """
    from app.database import SessionLocal
    from app.models_enhanced import User as UserTable
    
    db = SessionLocal()
    
    try:
        user_data = None
        
        # Try JWT token first
        if credentials and credentials.credentials:
            token_data = decode_access_token(credentials.credentials)
            user_id = token_data.get("user_id")
            
            result = db.execute(
                UserTable.select().where(UserTable.c.id == user_id)
            ).fetchone()
            
            if result:
                user_data = result
        
        # Try API key
        elif api_key and api_key.startswith(API_KEY_PREFIX):
            key_hash = hash_api_key(api_key)
            
            result = db.execute(
                UserTable.select().where(UserTable.c.api_key == key_hash)
            ).fetchone()
            
            if result:
                user_data = result
        
        if not user_data:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        if not user_data.is_active:
            raise HTTPException(status_code=403, detail="User account is disabled")
        
        role = Role(user_data.role)
        
        return User(
            id=user_data.id,
            email=user_data.email,
            name=user_data.name,
            role=role,
            permissions=ROLE_PERMISSIONS.get(role, []),
            is_active=user_data.is_active,
            tenant_id=user_data.tenant_id or "default"
        )
        
    finally:
        db.close()


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    api_key: Optional[str] = Depends(api_key_header)
) -> Optional[User]:
    """Get current user if authenticated, None otherwise."""
    try:
        return await get_current_user(credentials, api_key)
    except HTTPException:
        return None


# ============================================================================
# Permission Decorators
# ============================================================================

def require_permission(permission: Permission):
    """Decorator to require a specific permission."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, user: User = Depends(get_current_user), **kwargs):
            if not user.has_permission(permission):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {permission.value}"
                )
            return await func(*args, user=user, **kwargs)
        return wrapper
    return decorator


def require_any_permission(*permissions: Permission):
    """Decorator to require any of the specified permissions."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, user: User = Depends(get_current_user), **kwargs):
            if not user.has_any_permission(list(permissions)):
                raise HTTPException(
                    status_code=403,
                    detail="Permission denied"
                )
            return await func(*args, user=user, **kwargs)
        return wrapper
    return decorator


def require_role(role: Role):
    """Decorator to require a specific role."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, user: User = Depends(get_current_user), **kwargs):
            if user.role != role and user.role != Role.ADMIN:
                raise HTTPException(
                    status_code=403,
                    detail=f"Role required: {role.value}"
                )
            return await func(*args, user=user, **kwargs)
        return wrapper
    return decorator


def permission_dependency(permission: Permission):
    """FastAPI dependency enforcing a specific permission."""

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: {permission.value}"
            )
        return user

    return dependency


def permissions_dependency(*permissions: Permission):
    """FastAPI dependency enforcing any of the provided permissions."""

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if not user.has_any_permission(list(permissions)):
            raise HTTPException(status_code=403, detail="Permission denied")
        return user

    return dependency


# ============================================================================
# Audit Logging
# ============================================================================

async def log_audit(
    user: User,
    action: str,
    resource_type: str,
    resource_id: Optional[int],
    details: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None
):
    """Log an audit event."""
    from app.database import SessionLocal
    from app.models_enhanced import AuditLog
    
    db = SessionLocal()
    try:
        previous = db.execute(
            AuditLog.select().order_by(AuditLog.c.id.desc()).limit(1)
        ).fetchone()
        previous_hash = getattr(previous, "event_hash", None)

        payload = {
            "user_id": user.id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": details or {},
            "ip_address": request.client.host if request else None,
            "user_agent": request.headers.get("user-agent") if request else None,
            "timestamp": datetime.now(UTC).isoformat(),
            "previous_hash": previous_hash,
            "correlation_id": get_correlation_id(request),
            "tenant_id": user.tenant_id,
        }
        event_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

        db.execute(AuditLog.insert().values(
            user_id=user.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            ip_address=payload["ip_address"],
            user_agent=payload["user_agent"],
            correlation_id=payload["correlation_id"],
            previous_hash=previous_hash,
            event_hash=event_hash,
            retention_days=AUDIT_RETENTION_DAYS,
            tenant_id=user.tenant_id,
        ))
        db.commit()
    finally:
        db.close()
