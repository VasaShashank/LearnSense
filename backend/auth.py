"""Supabase-backed authentication dependencies for the FastAPI application.

The access token is validated by Supabase Auth's /auth/v1/user endpoint. This
avoids decoding a JWT without verification and keeps token-validation details
with the issuer. Application roles and tenant permissions remain the backend's
responsibility and must be checked separately.
"""

import os
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

_bearer_scheme = HTTPBearer(auto_error=False)


class AuthenticatedUser(BaseModel):
    """Minimal identity returned after Supabase verifies an access token."""

    id: str
    email: Optional[str] = None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    """Validate a Supabase access token and return its trusted user identity."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    # Supabase calls this key the publishable key in newer projects; older
    # projects commonly expose the equivalent anon key.
    api_key = (
        os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
        or os.getenv("SUPABASE_ANON_KEY", "").strip()
    )
    if not supabase_url or not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase authentication is not configured",
        )

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{supabase_url}/auth/v1/user",
                headers={
                    "apikey": api_key,
                    "Authorization": f"Bearer {credentials.credentials}",
                },
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication provider timed out",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication provider is unavailable",
        ) from exc

    if response.status_code in (401, 403):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not response.is_success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication provider could not validate the token",
        )

    try:
        user_data = response.json()
        user_id = user_data.get("id")
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("Supabase response did not contain a user ID")
        email = user_data.get("email")
        if email is not None and not isinstance(email, str):
            email = None
        return AuthenticatedUser(id=user_id, email=email)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication provider returned an invalid identity",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[AuthenticatedUser]:
    """Validate a supplied bearer token while allowing intentionally public calls."""
    if credentials is None:
        return None
    return await get_current_user(credentials=credentials)
