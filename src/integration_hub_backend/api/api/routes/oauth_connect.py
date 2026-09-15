"""OAuth2 authorization-code flow for connecting Gmail and Outlook mailboxes.

Users click "Connect Gmail / Outlook" in the SentinelBuild UI.  The browser
is redirected here → on to Google / Microsoft → back to our callback →
tokens stored encrypted in integration_credentials → browser returns to the
frontend with a success indicator.

State (nonce → company_id) is held in Redis for OAUTH_STATE_TTL_SECONDS to
survive the round-trip without keeping server-side session state.
"""

import json
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from integration_hub_backend.api.core.config import settings
from integration_hub_backend.api.core.db import AsyncSessionLocal
from integration_hub_backend.api.core.redis import get_redis_pool
from integration_hub_backend.api.crud.integration_credentials import create_credential
from integration_hub_backend.sentinelbuild_auth import SBUser, get_sb_user

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/oauth", tags=["oauth-connect"])

_GMAIL_SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/userinfo.email",
    ]
)
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Google Drive / Sheets — same OAuth client as Gmail, different scopes.
_GDRIVE_SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/userinfo.email",
    ]
)
_GSHEETS_SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/userinfo.email",
    ]
)

_MS_AUTH_BASE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
_OUTLOOK_SCOPES = "https://graph.microsoft.com/Mail.ReadWrite https://graph.microsoft.com/Mail.Send offline_access"

_STATE_PREFIX = "oauth_state:"


async def _save_state(redis: aioredis.Redis, nonce: str, payload: dict[str, Any]) -> None:
    await redis.setex(
        f"{_STATE_PREFIX}{nonce}",
        settings.OAUTH_STATE_TTL_SECONDS,
        json.dumps(payload),
    )


async def _pop_state(redis: aioredis.Redis, nonce: str) -> dict[str, Any] | None:
    key = f"{_STATE_PREFIX}{nonce}"
    raw = await redis.get(key)
    if raw is None:
        return None
    await redis.delete(key)
    state: dict[str, Any] = json.loads(raw)
    return state


def _ok_redirect(provider: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.FRONTEND_HOST}/oauth-connect-success?provider={provider}")


def _err_redirect(provider: str, reason: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.FRONTEND_HOST}/oauth-connect-error?provider={provider}&reason={reason}"
    )


# ── Gmail ─────────────────────────────────────────────────────────────────────


async def _build_gmail_authorize_url(name: str, current_user: SBUser) -> str:
    """Save round-trip state and return the Google consent URL.

    Shared by the browser-redirect endpoint and the JSON endpoint the
    chassis SPA calls (the SPA can't attach the Bearer header to a plain
    browser navigation, so it fetches this URL with dio then opens it).
    """
    if not settings.GMAIL_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Gmail OAuth is not configured"
        )
    nonce = secrets.token_urlsafe(24)
    # pre-existing bug fixed: get_redis is an async-generator FastAPI dependency
    # and does not support `async with` (raised TypeError at runtime);
    # get_redis_pool() returns the client directly, as the rest of the service does.
    redis = get_redis_pool()
    await _save_state(
        redis,
        nonce,
        {
            "company_id": current_user.org_id,
            "user_id": current_user.user_id,
            "credential_name": name,
            "provider": "gmail",
        },
    )
    params = {
        "client_id": settings.GMAIL_CLIENT_ID,
        "redirect_uri": settings.GMAIL_REDIRECT_URI,
        "response_type": "code",
        "scope": _GMAIL_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": nonce,
    }
    return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"


@router.get("/gmail/authorize", summary="Start Gmail OAuth2 connect flow")
async def gmail_authorize(
    name: str = "My Gmail",
    current_user: SBUser = Depends(get_sb_user),
) -> RedirectResponse:
    return RedirectResponse(await _build_gmail_authorize_url(name, current_user))


@router.get("/gmail/authorize-url", summary="Get Gmail OAuth2 consent URL (JSON)")
async def gmail_authorize_url(
    name: str = "My Gmail",
    current_user: SBUser = Depends(get_sb_user),
) -> dict[str, Any]:
    """JWT-authed: return the consent URL as JSON for SPA launch."""
    return {"authorize_url": await _build_gmail_authorize_url(name, current_user)}


@router.get("/gmail/callback", summary="Handle Gmail OAuth2 callback", include_in_schema=False)
async def gmail_callback(code: str, state: str) -> RedirectResponse:
    # pre-existing bug fixed: get_redis is an async-generator dep, not a context
    # manager; use the pool client directly.
    redis = get_redis_pool()
    ctx = await _pop_state(redis, state)
    if not ctx:
        return _err_redirect("gmail", "invalid_state")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GMAIL_CLIENT_ID,
                    "client_secret": settings.GMAIL_CLIENT_SECRET,
                    "redirect_uri": settings.GMAIL_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            token_resp.raise_for_status()
            tokens = token_resp.json()

        import uuid

        async with AsyncSessionLocal() as db:
            await create_credential(
                db,
                company_id=uuid.UUID(ctx["company_id"]),
                name=ctx["credential_name"],
                type_="oauth2",
                connector="gmail",
                secret_data={
                    "provider": "gmail",
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens.get("refresh_token", ""),
                    "token_type": tokens.get("token_type", "Bearer"),
                    "expires_in": tokens.get("expires_in", 3600),
                },
            )
        log.info("gmail_credential_stored", company_id=ctx["company_id"])
        return _ok_redirect("gmail")
    except Exception:
        log.exception("gmail_oauth_callback_failed")
        return _err_redirect("gmail", "token_exchange_failed")


# ── Google Drive / Sheets ─────────────────────────────────────────────────────
# Same Google OAuth client + token endpoint as Gmail; only the scopes and
# redirect URI differ. The ``connector`` (catalog key) is carried through
# state so one callback shape serves both, and the stored credential is
# tagged so the chassis "Connected" badge lights up.


async def _build_google_authorize_url(
    *,
    connector: str,
    scopes: str,
    redirect_uri: str,
    name: str,
    current_user: SBUser,
) -> str:
    if not settings.GMAIL_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Google OAuth is not configured"
        )
    nonce = secrets.token_urlsafe(24)
    # pre-existing bug fixed: get_redis is an async-generator dep, not a context
    # manager; use the pool client directly.
    redis = get_redis_pool()
    await _save_state(
        redis,
        nonce,
        {
            "company_id": current_user.org_id,
            "user_id": current_user.user_id,
            "credential_name": name,
            "provider": connector,
            "redirect_uri": redirect_uri,
        },
    )
    params = {
        "client_id": settings.GMAIL_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": nonce,
    }
    return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"


async def _google_callback(connector: str, code: str, state: str) -> RedirectResponse:
    # pre-existing bug fixed: get_redis is an async-generator dep, not a context
    # manager; use the pool client directly.
    redis = get_redis_pool()
    ctx = await _pop_state(redis, state)
    if not ctx:
        return _err_redirect(connector, "invalid_state")
    try:
        import uuid

        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GMAIL_CLIENT_ID,
                    "client_secret": settings.GMAIL_CLIENT_SECRET,
                    "redirect_uri": ctx.get("redirect_uri"),
                    "grant_type": "authorization_code",
                },
            )
            token_resp.raise_for_status()
            tokens = token_resp.json()
        async with AsyncSessionLocal() as db:
            await create_credential(
                db,
                company_id=uuid.UUID(ctx["company_id"]),
                name=ctx["credential_name"],
                type_="oauth2",
                connector=connector,
                secret_data={
                    "provider": connector,
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens.get("refresh_token", ""),
                    "token_type": tokens.get("token_type", "Bearer"),
                    "expires_in": tokens.get("expires_in", 3600),
                },
            )
        log.info("google_credential_stored", connector=connector, company_id=ctx["company_id"])
        return _ok_redirect(connector)
    except Exception:
        log.exception("google_oauth_callback_failed", connector=connector)
        return _err_redirect(connector, "token_exchange_failed")


@router.get("/google-drive/authorize-url", summary="Get Google Drive OAuth2 consent URL (JSON)")
async def google_drive_authorize_url(
    name: str = "My Google Drive",
    current_user: SBUser = Depends(get_sb_user),
) -> dict[str, Any]:
    return {
        "authorize_url": await _build_google_authorize_url(
            connector="google-drive",
            scopes=_GDRIVE_SCOPES,
            redirect_uri=settings.GOOGLE_DRIVE_REDIRECT_URI,
            name=name,
            current_user=current_user,
        )
    }


@router.get("/google-drive/callback", include_in_schema=False)
async def google_drive_callback(code: str, state: str) -> RedirectResponse:
    return await _google_callback("google-drive", code, state)


@router.get("/google-sheets/authorize-url", summary="Get Google Sheets OAuth2 consent URL (JSON)")
async def google_sheets_authorize_url(
    name: str = "My Google Sheets",
    current_user: SBUser = Depends(get_sb_user),
) -> dict[str, Any]:
    return {
        "authorize_url": await _build_google_authorize_url(
            connector="google-sheets",
            scopes=_GSHEETS_SCOPES,
            redirect_uri=settings.GOOGLE_SHEETS_REDIRECT_URI,
            name=name,
            current_user=current_user,
        )
    }


@router.get("/google-sheets/callback", include_in_schema=False)
async def google_sheets_callback(code: str, state: str) -> RedirectResponse:
    return await _google_callback("google-sheets", code, state)


# ── Outlook ───────────────────────────────────────────────────────────────────


async def _build_outlook_authorize_url(name: str, current_user: SBUser) -> str:
    if not settings.OUTLOOK_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Outlook OAuth is not configured",
        )
    nonce = secrets.token_urlsafe(24)
    # pre-existing bug fixed: get_redis is an async-generator dep, not a context
    # manager; use the pool client directly.
    redis = get_redis_pool()
    await _save_state(
        redis,
        nonce,
        {
            "company_id": current_user.org_id,
            "user_id": current_user.user_id,
            "credential_name": name,
            "provider": "outlook",
        },
    )
    base = _MS_AUTH_BASE.format(tenant=settings.OUTLOOK_TENANT_ID)
    params = {
        "client_id": settings.OUTLOOK_CLIENT_ID,
        "redirect_uri": settings.OUTLOOK_REDIRECT_URI,
        "response_type": "code",
        "scope": _OUTLOOK_SCOPES,
        "response_mode": "query",
        "prompt": "consent",
        "state": nonce,
    }
    return f"{base}/authorize?{urlencode(params)}"


@router.get("/outlook/authorize", summary="Start Outlook OAuth2 connect flow")
async def outlook_authorize(
    name: str = "My Outlook",
    current_user: SBUser = Depends(get_sb_user),
) -> RedirectResponse:
    return RedirectResponse(await _build_outlook_authorize_url(name, current_user))


@router.get("/outlook/authorize-url", summary="Get Outlook OAuth2 consent URL (JSON)")
async def outlook_authorize_url(
    name: str = "My Outlook",
    current_user: SBUser = Depends(get_sb_user),
) -> dict[str, Any]:
    """JWT-authed: return the consent URL as JSON for SPA launch."""
    return {"authorize_url": await _build_outlook_authorize_url(name, current_user)}


@router.get("/outlook/callback", summary="Handle Outlook OAuth2 callback", include_in_schema=False)
async def outlook_callback(code: str, state: str) -> RedirectResponse:
    # pre-existing bug fixed: get_redis is an async-generator dep, not a context
    # manager; use the pool client directly.
    redis = get_redis_pool()
    ctx = await _pop_state(redis, state)
    if not ctx:
        return _err_redirect("outlook", "invalid_state")

    try:
        base = _MS_AUTH_BASE.format(tenant=settings.OUTLOOK_TENANT_ID)
        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post(
                f"{base}/token",
                data={
                    "code": code,
                    "client_id": settings.OUTLOOK_CLIENT_ID,
                    "client_secret": settings.OUTLOOK_CLIENT_SECRET,
                    "redirect_uri": settings.OUTLOOK_REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "scope": _OUTLOOK_SCOPES,
                },
            )
            token_resp.raise_for_status()
            tokens = token_resp.json()

        import uuid

        async with AsyncSessionLocal() as db:
            await create_credential(
                db,
                company_id=uuid.UUID(ctx["company_id"]),
                name=ctx["credential_name"],
                type_="oauth2",
                connector="outlook",
                secret_data={
                    "provider": "outlook",
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens.get("refresh_token", ""),
                    "token_type": tokens.get("token_type", "Bearer"),
                    "expires_in": tokens.get("expires_in", 3600),
                },
            )
        log.info("outlook_credential_stored", company_id=ctx["company_id"])
        return _ok_redirect("outlook")
    except Exception:
        log.exception("outlook_oauth_callback_failed")
        return _err_redirect("outlook", "token_exchange_failed")
