from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.schemas.auth import Token, UserCreate, UserLogin, UserResponse
from app.schemas.common import ResponseEnvelope
from app.services.auth_service import auth_service, get_current_user

router = APIRouter()


@router.post("/register", response_model=ResponseEnvelope[UserResponse], status_code=status.HTTP_201_CREATED)
async def register_user(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    """Registers a new user account."""
    user = await auth_service.create_user(user_in, db)
    return ResponseEnvelope(
        success=True,
        data=UserResponse.from_orm(user),
        message="User registered successfully"
    )


@router.post("/login", response_model=Token)
async def login(login_data: UserLogin, db: AsyncSession = Depends(get_db)):
    """Authenticates credentials and returns a JWT access token."""
    user = await auth_service.authenticate_user(login_data.email, login_data.password, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        subject=user.id,
        role=user.role.value,
        org_id=user.org_id,
        expires_delta=access_token_expires
    )
    return Token(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=user.id,
        email=user.email,
        role=user.role
    )


@router.get("/me", response_model=ResponseEnvelope[UserResponse])
async def get_me(current_user: User = Depends(get_current_user)):
    """Returns profile for currently authenticated user."""
    return ResponseEnvelope(
        success=True,
        data=UserResponse.from_orm(current_user)
    )
