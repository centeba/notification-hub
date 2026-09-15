"""Redis cache helpers with typed get/set and TTL constants."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

# ── TTL constants (seconds) ───────────────────────────────────────────────────
TTL_COMPANY_SETTINGS = 3600  # 1 hour
TTL_ACTIVE_RULES = 300  # 5 minutes
TTL_TEMPLATE = 3600  # 1 hour
TTL_USER_PREFERENCES = 300  # 5 minutes
TTL_API_KEY = 300  # 5 minutes
TTL_RATE_LIMIT = 60  # 1 minute
TTL_USER_CONTACT = 300  # 5 minutes from User Master


def _key_company_settings(company_id: str) -> str:
    return f"notif:company:{company_id}:settings"


def _key_active_rules(company_id: str) -> str:
    return f"notif:company:{company_id}:rules:active"


def _key_template(template_id: str, lang: str) -> str:
    return f"notif:template:{template_id}:{lang}"


def _key_user_preferences(user_id: str) -> str:
    return f"notif:user:{user_id}:preferences"


def _key_api_key(prefix: str) -> str:
    return f"notif:apikey:{prefix}:valid"


def _key_user_contact(user_id: str) -> str:
    return f"notif:usercontact:{user_id}"


async def cache_get(redis: aioredis.Redis, key: str) -> Any | None:
    raw = await redis.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def cache_set(redis: aioredis.Redis, key: str, value: Any, ttl: int) -> None:
    await redis.setex(key, ttl, json.dumps(value, default=str))


async def cache_delete(redis: aioredis.Redis, key: str) -> None:
    await redis.delete(key)


async def cache_delete_pattern(redis: aioredis.Redis, pattern: str) -> None:
    """Delete all keys matching a pattern. Use sparingly — O(N) scan."""
    async for key in redis.scan_iter(match=pattern):
        await redis.delete(key)
