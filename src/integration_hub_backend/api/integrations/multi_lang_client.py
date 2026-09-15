"""Async HTTP client for the Multi-Lang translation service with Redis caching."""

from typing import Any

import httpx
import redis.asyncio as aioredis
import structlog

from integration_hub_backend.api.core.config import settings

log = structlog.get_logger(__name__)

_TTL_TRANSLATION = 3600  # 1 hour — matches multi-lang service own TTL


def _cache_key(locale: str, namespace: str) -> str:
    return f"notif:i18n:{locale}:{namespace}"


class MultiLangClient:
    """Fetches translation namespaces from the multi-lang service.

    Falls back to ``en-US`` transparently (the upstream service already does
    this, but we handle HTTP errors gracefully here).
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis
        self._client = httpx.AsyncClient(
            base_url=settings.MULTI_LANG_URL,
            timeout=httpx.Timeout(5.0, connect=2.0),
        )

    async def get_translations(self, namespace: str, locale: str = "en-US") -> dict[str, Any]:
        """Return translation dict for *namespace* and *locale*.

        Returns an empty dict on any failure so callers can degrade gracefully.
        """
        cache_key = _cache_key(locale, namespace)

        # Check local Redis cache first (avoids hitting multi-lang on every call)
        try:
            import json

            raw = await self._redis.get(cache_key)
            if raw:
                cached: dict[str, Any] = json.loads(raw)
                return cached
        except Exception:
            pass

        try:
            resp = await self._client.get(
                f"/api/v1/translations/{namespace}", params={"locale": locale}
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json().get("data", {})
        except httpx.HTTPStatusError as e:
            log.warning(
                "multi_lang_http_error",
                namespace=namespace,
                locale=locale,
                status=e.response.status_code,
            )
            return {}
        except Exception as e:
            log.error("multi_lang_error", namespace=namespace, locale=locale, error=str(e))
            return {}

        try:
            import json

            await self._redis.setex(cache_key, _TTL_TRANSLATION, json.dumps(data))
        except Exception:
            pass

        return data

    async def close(self) -> None:
        await self._client.aclose()
