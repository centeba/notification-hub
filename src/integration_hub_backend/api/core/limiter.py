"""SlowAPI rate limiter configuration.

Storage is **Redis-backed** so limits apply GLOBALLY across every replica —
SlowAPI's default in-memory storage is per-process, so behind N replicas the
effective limit becomes N× the intended value. ``in_memory_fallback_enabled``
keeps per-process limiting alive if Redis is briefly unreachable rather than
erroring requests.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from integration_hub_backend.api.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    storage_uri=settings.REDIS_URL,
    in_memory_fallback_enabled=True,
)
