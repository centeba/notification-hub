"""Async Redis client and dependency injection."""

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from integration_hub_backend.api.core.config import settings

_redis_pool: aioredis.Redis | None = None


def get_redis_pool() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )
    return _redis_pool


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    redis = get_redis_pool()
    yield redis


async def run_once(name: str, ttl_seconds: int = 300, *, fail_open: bool = False) -> bool:
    """Cross-replica "should THIS process run one-shot startup task ``name``?".

    Thin wrapper over the shared ``smart_llm.service_runtime.run_once`` (the
    canonical primitive) bound to this service's Redis pool. Defaults to
    **fail-closed** on a Redis error (skip the task); callers whose task is
    idempotent-and-must-run pass ``fail_open=True`` explicitly.
    """
    from smart_llm.service_runtime import run_once as _run_once

    # smart_llm.service_runtime is untyped, so the awaited result is Any;
    # pin it to bool for the declared return type.
    ran: bool = await _run_once(
        get_redis_pool(), name, ttl_seconds=ttl_seconds, fail_open=fail_open
    )
    return ran


async def close_redis() -> None:
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None
