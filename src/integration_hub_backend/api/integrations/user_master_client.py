"""Async HTTP client for the User Master API with Redis caching and circuit breaker."""

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import redis.asyncio as aioredis
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from integration_hub_backend.api.core.cache import (
    TTL_USER_CONTACT,
    _key_user_contact,
    cache_get,
    cache_set,
)
from integration_hub_backend.api.core.config import settings

log = structlog.get_logger(__name__)


@dataclass
class UserContact:
    user_id: uuid.UUID
    email: str
    phone: str | None
    full_name: str | None
    language: str | None  # user's preferred language override
    company_id: uuid.UUID | None


_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            base_url=settings.USER_MASTER_API_URL,
            headers={
                "X-API-Key": settings.USER_MASTER_API_KEY,
                # user-master's M2M /private/* endpoints gate on X-Internal-Key
                # (== INTERNAL_API_KEY). Recipient resolution uses those.
                "X-Internal-Key": settings.USER_MASTER_API_KEY,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


class UserMasterClient:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis
        self._client = get_http_client()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _get(self, path: str) -> dict[str, Any]:
        response = await self._client.get(path)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload

    async def get_user_contact(self, user_id: uuid.UUID) -> UserContact | None:
        """Fetch a single user's contact info, with Redis caching."""
        cache_key = _key_user_contact(str(user_id))
        cached = await cache_get(self._redis, cache_key)
        if cached:
            fields: dict[str, Any] = {
                k: uuid.UUID(v) if k in ("user_id", "company_id") and v else v
                for k, v in cached.items()
            }
            return UserContact(**fields)

        try:
            data = await self._get(f"/users/{user_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            log.error(
                "user_master_get_user_error", user_id=str(user_id), status=e.response.status_code
            )
            raise
        except Exception as e:
            log.error("user_master_get_user_error", user_id=str(user_id), error=str(e))
            raise

        contact = UserContact(
            user_id=uuid.UUID(data["id"]),
            email=data["email"],
            phone=data.get("phone"),
            full_name=data.get("full_name"),
            language=data.get("preferred_language"),
            company_id=uuid.UUID(data["company_id"]) if data.get("company_id") else None,
        )
        await cache_set(
            self._redis,
            cache_key,
            {
                "user_id": str(contact.user_id),
                "email": contact.email,
                "phone": contact.phone,
                "full_name": contact.full_name,
                "language": contact.language,
                "company_id": str(contact.company_id) if contact.company_id else None,
            },
            TTL_USER_CONTACT,
        )
        return contact

    async def get_users_by_role(self, company_id: uuid.UUID, role: str) -> list[UserContact]:
        """Fetch all users with a given role in a company."""
        try:
            data = await self._get(f"/company/users?role={role}&company_id={company_id}&limit=1000")
        except Exception as e:
            log.error(
                "user_master_get_users_by_role_error",
                company_id=str(company_id),
                role=role,
                error=str(e),
            )
            return []

        return [
            UserContact(
                user_id=uuid.UUID(u["id"]),
                email=u["email"],
                phone=u.get("phone"),
                full_name=u.get("full_name"),
                language=u.get("preferred_language"),
                company_id=company_id,
            )
            for u in data.get("data", [])
        ]

    async def get_company_users(self, company_id: uuid.UUID) -> list[UserContact]:
        """Fetch all users in a company via the M2M /private endpoint (the
        /company/users route is JWT-gated and unreachable M2M)."""
        try:
            data = await self._get(f"/private/users/by-company/{company_id}")
        except Exception as e:
            log.error(
                "user_master_get_company_users_error", company_id=str(company_id), error=str(e)
            )
            return []

        # The private endpoint returns a bare list of UserContact objects.
        rows = data if isinstance(data, list) else data.get("data", [])
        out: list[UserContact] = []
        for u in rows:
            uid = u.get("user_id") or u.get("id")
            if not uid:
                continue
            out.append(
                UserContact(
                    user_id=uuid.UUID(str(uid)),
                    email=u.get("email"),
                    phone=u.get("phone"),
                    full_name=u.get("full_name"),
                    language=u.get("language") or u.get("preferred_language"),
                    company_id=company_id,
                )
            )
        return out
