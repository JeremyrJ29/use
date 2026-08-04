from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from use.config import get_settings

settings = get_settings()

ALGORITHM = settings.jwt_algorithm


def create_access_token(
    user_id: str,
    scopes: list[str],
    expires_delta: timedelta | None = None,
) -> str:
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_expiry_minutes)
    expire = datetime.utcnow() + expires_delta
    payload: dict[str, Any] = {
        "sub": user_id,
        "scopes": scopes,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return payload
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc
