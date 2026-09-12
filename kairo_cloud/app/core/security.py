import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against its bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Computes a bcrypt hash for a plain password."""
    return pwd_context.hash(password)


def create_access_token(
    subject: Union[str, Any],
    role: str = "VIEWER",
    org_id: Optional[str] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Generates a signed JWT token."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "exp": expire,
        "iat": now,
        "sub": str(subject),
        "role": role,
        "org_id": org_id
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decodes and validates a JWT token."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def generate_api_key(prefix: str = "kairo_live") -> str:
    """Generates a secure, 32-byte hex API key for vehicle authentication."""
    random_bytes = secrets.token_hex(24)
    return f"{prefix}_{random_bytes}"


def hash_api_key(api_key: str) -> str:
    """Computes SHA-256 hash of API key for safe database storage."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()
