from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from use.auth.jwt import create_access_token

router = APIRouter()

VALID_SCOPES = {"read", "write", "review", "admin"}


class TokenRequest(BaseModel):
    user_id: str
    scopes: list[str] = ["read"]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/token", response_model=TokenResponse, tags=["auth"])
async def dev_token(body: TokenRequest) -> TokenResponse:
    """Development-only token generation endpoint. Not for production use."""
    scopes = [s for s in body.scopes if s in VALID_SCOPES]
    token = create_access_token(user_id=body.user_id, scopes=scopes)
    return TokenResponse(access_token=token)
