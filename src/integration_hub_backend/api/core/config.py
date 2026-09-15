"""Application configuration loaded from environment variables."""

import base64
import hashlib
import secrets

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    # ── Project ───────────────────────────────────────────────────────────────
    PROJECT_NAME: str = "Integration Hub"
    ENVIRONMENT: str = "local"
    API_V1_STR: str = "/api/v1"

    # The single domain vertical this deployment serves (e.g. "restoration",
    # "wealth"). SentinelBuild is deployed one instance per domain; when set,
    # the AI-skill/agent /sync endpoints reject any artifact whose source_app
    # differs, so a deployment can only ever ingest its own domain's AI
    # artifacts. Empty (default) = no enforcement (dev / single-domain).
    APP_SOURCE: str = ""

    # ── Security ──────────────────────────────────────────────────────────────
    # Left blank by default so set_defaults() can tell "unset" from
    # "explicitly configured" — filled with a random per-process value for
    # local/dev convenience, but that fallback would silently invalidate every
    # JWT (and every M2M call, for INTERNAL_SERVICE_SECRET below) on every
    # restart/replica if it ever ran that way in production.
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours

    # Internal service-to-service secret (Bearer token for email/sms/webhook calls)
    INTERNAL_SERVICE_SECRET: str = ""

    # Optional inbound-webhook HMAC secret. When set, /events/ingest requires a
    # valid X-Hub-Signature-256 (+ optional X-Sentinel-Timestamp for replay
    # protection) IN ADDITION to the API key — a second factor for signed
    # senders. Unset (default) = API-key auth only, unchanged.
    WEBHOOK_SECRET: str = ""

    # Canonical M2M key — accepted via ``X-Internal-Key`` header on
    # internal endpoints. Phase 1.4 of the architecture assessment
    # consolidates the two M2M secrets onto this one; ``INTERNAL_SERVICE_SECRET``
    # is preserved as a transitional Bearer alias on the verifier so
    # existing callers (mit-stack agent activities, esign → integration-hub)
    # keep working during rollout.
    INTERNAL_API_KEY: str = ""

    # AES-256-GCM key for PII field encryption (base64-encoded 32 bytes)
    FIELD_ENCRYPTION_KEY: str = ""

    # Fernet key for smart-llm LLM API key encryption.
    # If not set, derived from SECRET_KEY via SHA-256 so it's always valid.
    LLM_ENCRYPTION_KEY: str = ""

    @property
    def fernet_llm_key(self) -> str:
        """Return a valid URL-safe base64-encoded 32-byte Fernet key."""
        if self.LLM_ENCRYPTION_KEY:
            return self.LLM_ENCRYPTION_KEY
        # Derive deterministically from SECRET_KEY so tests and dev work
        # without extra config. Production should set LLM_ENCRYPTION_KEY.
        raw = hashlib.sha256(self.SECRET_KEY.encode()).digest()
        return base64.urlsafe_b64encode(raw).decode()

    # ── User Master Integration ───────────────────────────────────────────────
    USER_MASTER_API_URL: str = "http://localhost:8000/api/v1"
    USER_MASTER_API_KEY: str = ""

    # ── Delivery Service URLs ─────────────────────────────────────────────────
    EMAIL_SERVICE_URL: str = "http://email-service:8002"
    SMS_SERVICE_URL: str = "http://sms-service:8003"
    WEBHOOK_SERVICE_URL: str = "http://webhook-service:8004"

    # ── Multi-Lang Service ────────────────────────────────────────────────────
    MULTI_LANG_URL: str = "http://multi-lang-service:8001"

    # ── CORS ──────────────────────────────────────────────────────────────────
    # pydantic-settings 2.x JSON-decodes complex-type fields (list, dict)
    # from env BEFORE field_validator runs, so a CSV value crashes the
    # service at startup. Workaround: store the raw env value as a
    # plain str and expose a @property that handles both CSV and
    # JSON-array shapes — same pattern pages-api and esignature use.
    # Compose env var name stays BACKEND_CORS_ORIGINS for back-compat.
    BACKEND_CORS_ORIGINS: str = ""
    FRONTEND_HOST: str = "http://localhost:3000"

    @property
    def backend_cors_origins_list(self) -> list[str]:
        raw = self.BACKEND_CORS_ORIGINS.strip()
        if not raw:
            return []
        if raw.startswith("["):
            import json as _json

            try:
                parsed = _json.loads(raw)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        return [i.strip() for i in raw.split(",") if i.strip()]

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "changethis"
    POSTGRES_DB: str = "notification_hub"

    DATABASE_URL: str = ""  # canonical override; preferred when set

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        if self.DATABASE_URL:
            u = self.DATABASE_URL
            return u if "+asyncpg" in u else u.replace("postgresql://", "postgresql+asyncpg://", 1)
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""

    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/0"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # ── Temporal ──────────────────────────────────────────────────────────────
    TEMPORAL_HOST: str = "temporal"
    TEMPORAL_PORT: int = 7233
    TEMPORAL_NAMESPACE: str = "integration-hub"
    # Set to point at Temporal Cloud instead of a self-hosted server — the
    # client automatically enables TLS whenever this is non-empty (Temporal
    # Cloud's API-key auth requires it). Leave blank for self-hosted Temporal.
    TEMPORAL_API_KEY: str = ""

    @property
    def TEMPORAL_ADDRESS(self) -> str:
        return f"{self.TEMPORAL_HOST}:{self.TEMPORAL_PORT}"

    # ── OAuth2 Email Connect (Gmail / Outlook) ────────────────────────────────
    GMAIL_CLIENT_ID: str = ""
    GMAIL_CLIENT_SECRET: str = ""
    GMAIL_REDIRECT_URI: str = "http://localhost:8005/api/v1/oauth/gmail/callback"

    # Google Drive / Sheets reuse the SAME Google OAuth client as Gmail
    # (GMAIL_CLIENT_ID/SECRET) — Google clients are scope-agnostic. The
    # operator only has to (1) enable the Drive + Sheets APIs on that
    # project, (2) register these redirect URIs on the client, and (3) add
    # the Drive/Sheets scopes to the consent screen. No new secret needed.
    GOOGLE_DRIVE_REDIRECT_URI: str = "http://localhost:8005/api/v1/oauth/google-drive/callback"
    GOOGLE_SHEETS_REDIRECT_URI: str = "http://localhost:8005/api/v1/oauth/google-sheets/callback"

    OUTLOOK_CLIENT_ID: str = ""
    OUTLOOK_CLIENT_SECRET: str = ""
    OUTLOOK_TENANT_ID: str = "common"
    OUTLOOK_REDIRECT_URI: str = "http://localhost:8005/api/v1/oauth/outlook/callback"

    OAUTH_STATE_TTL_SECONDS: int = 300

    # ── Frontend (for post-OAuth redirects) ───────────────────────────────────
    # FRONTEND_HOST is declared once above in the CORS section (same default);
    # the pre-existing duplicate field here was removed (pydantic kept only the
    # last, so behaviour is unchanged).

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 100

    # ── Sentry ────────────────────────────────────────────────────────────────
    SENTRY_DSN: str = ""

    # ── SMS Providers ─────────────────────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""

    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    AWS_SNS_SMS_SENDER_ID: str = "NotifHub"

    @model_validator(mode="after")
    # Pre-existing bug (fixed): the return annotation named the enclosing
    # ``Settings`` class, which isn't bound yet while the class body runs — with
    # no ``from __future__ import annotations`` this raised ``NameError`` at
    # import, breaking config load (and every test that imports it). Quote the
    # forward reference so it stays a string until it's actually needed.
    def set_defaults(self) -> "Settings":
        if self.ENVIRONMENT != "production":
            # Stable for the life of this process (not regenerated per
            # request), but intentionally not persisted anywhere so it's
            # never mistaken for a real configured secret.
            if not self.SECRET_KEY:
                self.SECRET_KEY = secrets.token_urlsafe(32)
            if not self.INTERNAL_SERVICE_SECRET:
                self.INTERNAL_SERVICE_SECRET = secrets.token_urlsafe(32)
            return self
        errors: list[str] = []
        if not self.SECRET_KEY:
            errors.append(
                "SECRET_KEY must be set in production — left unset, every "
                "restart or replica mints a different key, silently "
                "invalidating all existing JWTs"
            )
        if not self.INTERNAL_SERVICE_SECRET:
            errors.append(
                "INTERNAL_SERVICE_SECRET must be set in production — left "
                "unset, every restart or replica mints a different value, "
                "breaking M2M auth to the email/sms/webhook services"
            )
        if not self.FIELD_ENCRYPTION_KEY:
            errors.append(
                "FIELD_ENCRYPTION_KEY must be set in production — left unset, "
                "PII/webhook-secret field encryption derives its AES key from "
                "an empty string (a world-known constant), making all "
                "ciphertext trivially decryptable (SEC H5)"
            )
        if errors:
            raise ValueError(
                "Production configuration errors:\n" + "\n".join(f"  • {e}" for e in errors)
            )
        return self


settings = Settings()
