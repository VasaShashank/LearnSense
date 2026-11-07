"""Supabase-backed authentication dependencies for the FastAPI application.

The access token is validated by Supabase Auth's /auth/v1/user endpoint. This
avoids decoding a JWT without verification and keeps token-validation details
with the issuer. Application roles and tenant permissions remain the backend's
responsibility and must be checked separately.
"""

import os
from typing import Optional

import logging

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from backend.api_errors import ApiError

logger = logging.getLogger(__name__)

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
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED, "AUTHENTICATION_REQUIRED",
            "Missing bearer access token",
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
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "AUTH_NOT_CONFIGURED",
            "Supabase authentication is not configured", recoverable=True,
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
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "AUTH_PROVIDER_TIMEOUT",
            "Authentication provider timed out", recoverable=True,
        ) from exc
    except httpx.RequestError as exc:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "AUTH_PROVIDER_UNAVAILABLE",
            "Authentication provider is unavailable", recoverable=True,
        ) from exc

    if response.status_code in (401, 403):
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN",
            "Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not response.is_success:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "AUTH_PROVIDER_ERROR",
            "Authentication provider could not validate the token", recoverable=True,
        )

    try:
        user_data = response.json()
        user_id = user_data.get("id")
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("Supabase response did not contain a user ID")
        email = user_data.get("email")
        if email is not None and not isinstance(email, str):
            email = None
        user = AuthenticatedUser(id=user_id, email=email)
    except (ValueError, TypeError) as exc:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED, "INVALID_IDENTITY",
            "Authentication provider returned an invalid identity",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    await _reject_disabled_account(user.id)
    return user


async def _reject_disabled_account(user_id: str) -> None:
    """Single enforcement point for locally disabled accounts (fails closed)."""
    from backend.services.user_service import get_user_service

    try:
        disabled = await get_user_service().is_disabled(user_id)
    except Exception as exc:
        logger.error("Account status lookup failed: %s", type(exc).__name__)
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "ACCOUNT_STATUS_UNAVAILABLE",
            "Account status could not be verified", recoverable=True,
        ) from exc
    if disabled:
        raise ApiError(status.HTTP_403_FORBIDDEN, "ACCOUNT_DISABLED", "This account has been disabled.")


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[AuthenticatedUser]:
    """Validate a supplied bearer token while allowing intentionally public calls."""
    if credentials is None:
        return None
    return await get_current_user(credentials=credentials)
