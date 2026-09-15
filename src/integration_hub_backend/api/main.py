"""FastAPI application entry point — notification-api service."""

from collections.abc import Awaitable, Callable

import sentry_sdk
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from integration_hub_backend.api.api.main import api_router
from integration_hub_backend.api.core.config import settings
from integration_hub_backend.api.core.limiter import limiter
from integration_hub_backend.api.core.redis import close_redis
from integration_hub_backend.api.core.subscription_hub import close_subscription_hub
from integration_hub_backend.api.integrations.user_master_client import close_http_client
from integration_hub_backend.api.temporal.client import close_temporal_client

log = structlog.get_logger(__name__)

# ── Sentry ────────────────────────────────────────────────────────────────────
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=0.1,
    )

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Integration Hub API",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    # Disable docs in production
    docs_url=f"{settings.API_V1_STR}/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url=f"{settings.API_V1_STR}/redoc" if settings.ENVIRONMENT != "production" else None,
)

# ── Observability (Prometheus /metrics + Sentry + OTEL) ───────────────────────
# Each piece is opt-in via env (SENTRY_DSN, OTEL_EXPORTER_OTLP_ENDPOINT);
# the helper no-ops gracefully when its libs aren't installed.
from smart_llm.observability import install_observability  # noqa: E402

install_observability(app, service_name="integration-hub-api", environment=settings.ENVIRONMENT)

from integration_hub_backend._platform.rate_limit import install_rate_limit  # noqa: E402

# Gate 7: blanket per-IP rate limit — no-op until RATE_LIMIT_REDIS_URL is set.
# Coexists with the fine-grained SlowAPI limits on login/2FA; this is the
# platform-wide abuse ceiling on every other path.
install_rate_limit(app, service_name="integration-hub")

# ── Readiness probe + uniform 500 handler ─────────────────────────────────────
# /healthz deep-checks DB+Redis+Temporal (readiness); the shallow /health below
# stays liveness-only. The exception handler returns a non-leaking
# {error_code, request_id} 500 envelope.
from smart_llm.service_runtime import (  # noqa: E402
    add_readiness_route,
    db_check,
    install_exception_handler,
    redis_check,
    temporal_check,
)

from integration_hub_backend.api.core.db import AsyncSessionLocal  # noqa: E402
from integration_hub_backend.api.core.redis import get_redis_pool  # noqa: E402
from integration_hub_backend.api.temporal.client import get_temporal_client  # noqa: E402

install_exception_handler(app, service_name="integration-hub-api")
add_readiness_route(
    app,
    service_name="integration-hub-api",
    checks={
        "db": db_check(AsyncSessionLocal),
        "redis": redis_check(get_redis_pool),
        "temporal": temporal_check(get_temporal_client),
    },
)

# ── Rate Limiting ─────────────────────────────────────────────────────────────
app.state.limiter = limiter
# slowapi's handler is typed with the concrete RateLimitExceeded, which does not
# match Starlette's Callable[[Request, Exception], ...] handler type (a known
# slowapi/starlette variance gap); the runtime contract is correct.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)

# ── CORS ──────────────────────────────────────────────────────────────────────
allowed_origins = list(settings.backend_cors_origins_list)
if settings.FRONTEND_HOST not in allowed_origins:
    allowed_origins.append(settings.FRONTEND_HOST)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# ── Idempotency (SB-03) ─────────────────────────────────────────────────────
# Uniform Idempotency-Key replay for mutating requests, backed by this service's
# Redis. Inert unless a client sends the header; supersedes the per-endpoint
# ad-hoc dedup (e.g. the events route's workflow-id trick) with one contract.
from smart_llm.api.middleware import add_idempotency_middleware  # noqa: E402

add_idempotency_middleware(app, get_redis_pool)

# ── Request Logging Middleware ────────────────────────────────────────────────
import time as _time
import uuid as _uuid

_SKIP_PATHS = frozenset(["/health"])


@app.middleware("http")
async def request_logging(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path in _SKIP_PATHS:
        return await call_next(request)
    request_id = request.headers.get("X-Request-ID", str(_uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    start = _time.perf_counter()
    response = await call_next(request)
    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((_time.perf_counter() - start) * 1000, 1),
    )
    response.headers["X-Request-ID"] = request_id
    return response


# ── Security Headers Middleware ───────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "integration-api"}


# ── Lifecycle ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup() -> None:
    log.info("notification_api_starting")

    # Initialise smart-llm's DatabaseKeyStore using our PostgreSQL engine.
    # This creates the `llm_api_keys` table if it doesn't exist and wires up
    # the singleton used by create_agents_router / get_company_api_key.
    from smart_llm.api.llm_service import get_key_store

    from integration_hub_backend.api.core.db import engine
    from integration_hub_backend.api.core.redis import run_once

    # `get_key_store` wires the in-process singleton on EVERY replica (required).
    # The `llm_api_keys` DDL is now owned by Alembic (migration 027_llm_api_keys,
    # applied by migrate-on-boot before the app serves) rather than a runtime
    # create_all() side-effect here — deterministic and ordered ahead of the
    # services that read the table. See Gate 8.
    get_key_store(engine=engine, encryption_key=settings.fernet_llm_key)
    log.info("smart_llm_key_store_ready")

    # Phase M — ensure the AI Admin Elasticsearch index exists. Best-
    # effort: returns ``False`` and logs a warning when ES is
    # unreachable; the search endpoint then falls back to empty
    # results and the AI Admin UI uses its in-memory filter.
    # One replica per boot window creates it (run_once) — the index is a shared
    # side-effect and search degrades gracefully on the followers until it lands.
    from smart_llm.api import ai_search_index

    if await run_once("ai_search_ensure_index", fail_open=True):  # idempotent DDL
        ok = await ai_search_index.ensure_index()
        if ok:
            log.info("ai_search_index_ready")
        else:
            log.warning("ai_search_index_unavailable")
    else:
        log.info("ai_search_index_ensure_skipped_other_replica")

    # Phase 1 (R1) — discover packs declared via the ``sb_pack``
    # entry-point group, then install each: register its search
    # entities, persist its RBAC permissions, mount any
    # router_factories under ``/api/{pack_name}/v1/``. Idempotent on
    # restart. Wrapped in try/except so chassis-only boots (sb_core
    # uninstalled, entry-point group empty, etc.) still come up.
    # NOT run_once-guarded, deliberately: router mounting MUST happen on every
    # replica (each process serves the routes), and the DB writes are idempotent
    # upserts (INSERT … ON CONFLICT DO UPDATE), so concurrent replicas are safe.
    try:
        from integration_hub_backend.api.core.db import AsyncSessionLocal
        from integration_hub_backend.api.services.ai_search_registry import (
            register_entity,
        )
        from integration_hub_backend.api.services.pack_bootstrap import (
            bootstrap_packs,
        )

        summary = await bootstrap_packs(
            app,
            session_factory=AsyncSessionLocal,
            register_search_entity=register_entity,
        )
        log.info("sb_packs_installed", **summary)
    except Exception as exc:  # noqa: BLE001
        log.warning("sb_pack_discovery_skipped", error=str(exc))


@app.on_event("shutdown")
async def shutdown() -> None:
    # Drain the WS fan-out hub (stop its reader, close the shared pubsub)
    # before closing the Redis pool it borrows a connection from.
    await close_subscription_hub()
    await close_redis()
    await close_http_client()
    await close_temporal_client()
    log.info("notification_api_shutdown")
