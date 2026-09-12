import logging
from typing import List, Optional
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token, get_password_hash, hash_api_key, verify_password
from app.models.user import User, UserRole
from app.models.vehicle import Vehicle, VehicleStatus
from app.schemas.auth import UserCreate

logger = logging.getLogger(__name__)
security_bearer = HTTPBearer(auto_error=False)


class AuthService:
    """Service handling User authentication, RBAC, and Vehicle API Key verification."""

    async def authenticate_user(
        self,
        email: str,
        password: str,
        db: AsyncSession
    ) -> Optional[User]:
        stmt = select(User).where(User.email == email)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()
        if not user or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    async def create_user(
        self,
        user_in: UserCreate,
        db: AsyncSession
    ) -> User:
        stmt = select(User).where(User.email == user_in.email)
        res = await db.execute(stmt)
        if res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email already exists"
            )

        user = User(
            email=user_in.email,
            hashed_password=get_password_hash(user_in.password),
            full_name=user_in.full_name,
            role=user_in.role,
            is_active=True
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    async def verify_vehicle_api_key(
        self,
        vehicle_id: str,
        api_key: str,
        db: AsyncSession
    ) -> Optional[Vehicle]:
        """Validates vehicle API key against SHA-256 hash stored in DB."""
        if not api_key:
            return None

        hashed_key = hash_api_key(api_key)
        stmt = select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.api_key_hash == hashed_key,
            Vehicle.is_active == True
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()


auth_service = AuthService()


async def get_current_user(
    auth_creds: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    db: AsyncSession = Depends(get_db)
) -> User:
    """FastAPI dependency for authenticating user via JWT Bearer token."""
    if not auth_creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth_creds.credentials
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject")

    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def require_role(allowed_roles: List[UserRole]):
    """Role-based access control dependency factory."""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted for role {current_user.role.value}"
            )
        return current_user
    return role_checker
