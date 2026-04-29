"""OAuth/OIDC authentication — Google + generic OIDC (Keycloak, Authentik, etc.)."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from brainycat import db
from brainycat.config import settings

router = APIRouter(prefix="/api/v1/auth/oauth", tags=["oauth"])


@router.get("/google")
async def google_login(request: Request) -> RedirectResponse:
    """Redirect to Google OAuth."""
    client_id = getattr(settings, "google_client_id", "")
    if not client_id:
        return RedirectResponse("/")
    redirect_uri = str(request.base_url) + "api/v1/auth/oauth/google/callback"
    url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&redirect_uri={redirect_uri}"
        f"&response_type=code&scope=openid+email+profile"
    )
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(code: str, request: Request) -> RedirectResponse:
    """Handle Google OAuth callback."""
    client_id = getattr(settings, "google_client_id", "")
    client_secret = getattr(settings, "google_client_secret", "")
    redirect_uri = str(request.base_url) + "api/v1/auth/oauth/google/callback"

    async with httpx.AsyncClient() as client:
        # Exchange code for token
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            return RedirectResponse("/?error=oauth_failed")
        tokens = token_resp.json()

        # Get user info
        userinfo = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        info = userinfo.json()

    email = info.get("email", "")
    name = info.get("name", email.split("@")[0])

    # Find or create user
    user = await db.fetch_one("SELECT id FROM users WHERE email = $1", email)
    if not user:
        import secrets

        user = await db.fetch_one(
            "INSERT INTO users (username, email, password_hash, api_key, role) VALUES ($1, $2, '', $3, 'user') RETURNING id",
            name,
            email,
            secrets.token_hex(16),
        )

    # Set session cookie
    from brainycat.routes.auth import create_session_token

    token = await create_session_token(str(user["id"]))
    response = RedirectResponse("/")
    response.set_cookie("session", token, httponly=True, max_age=86400 * 30)
    return response


@router.get("/oidc")
async def oidc_login(request: Request) -> RedirectResponse:
    """Redirect to generic OIDC provider."""
    oidc_url = getattr(settings, "oidc_issuer", "")
    client_id = getattr(settings, "oidc_client_id", "")
    if not oidc_url or not client_id:
        return RedirectResponse("/?error=oidc_not_configured")
    redirect_uri = str(request.base_url) + "api/v1/auth/oauth/oidc/callback"
    url = f"{oidc_url}/protocol/openid-connect/auth?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&scope=openid+email+profile"
    return RedirectResponse(url)


@router.get("/oidc/callback")
async def oidc_callback(code: str, request: Request) -> RedirectResponse:
    """Handle generic OIDC callback."""
    oidc_url = getattr(settings, "oidc_issuer", "")
    client_id = getattr(settings, "oidc_client_id", "")
    client_secret = getattr(settings, "oidc_client_secret", "")
    redirect_uri = str(request.base_url) + "api/v1/auth/oauth/oidc/callback"

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            f"{oidc_url}/protocol/openid-connect/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            return RedirectResponse("/?error=oidc_failed")
        tokens = token_resp.json()

        userinfo = await client.get(
            f"{oidc_url}/protocol/openid-connect/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        info = userinfo.json()

    email = info.get("email", "")
    name = info.get("preferred_username", info.get("name", email.split("@")[0]))

    user = await db.fetch_one("SELECT id FROM users WHERE email = $1", email)
    if not user:
        import secrets

        user = await db.fetch_one(
            "INSERT INTO users (username, email, password_hash, api_key, role) VALUES ($1, $2, '', $3, 'user') RETURNING id",
            name,
            email,
            secrets.token_hex(16),
        )

    from brainycat.routes.auth import create_session_token

    token = await create_session_token(str(user["id"]))
    response = RedirectResponse("/")
    response.set_cookie("session", token, httponly=True, max_age=86400 * 30)
    return response
