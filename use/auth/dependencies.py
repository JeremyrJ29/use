from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from use.auth.jwt import decode_token

_bearer = HTTPBearer()

VALID_SCOPES = {"read", "write", "review", "admin"}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict[str, Any]:
    try:
        payload = decode_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return payload


def require_scope(scope: str):
    """Dependency factory: raises 403 if the authenticated user lacks the required scope."""

    async def _check(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        user_scopes: list[str] = user.get("scopes", [])
        if scope not in user_scopes and "admin" not in user_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Scope '{scope}' required.",
            )
        return user

    return _check
