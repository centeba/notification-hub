"""NotificationCompanySettings ORM model and Pydantic schemas."""

import uuid
from typing import Any

from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from integration_hub_backend.api.core.db import Base


class NotificationCompanySettings(Base):
    __tablename__ = "notification_company_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, index=True
    )
    default_language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    sms_provider: Mapped[str] = mapped_column(String(20), default="twilio", nullable=False)
    # Encrypted JSON blob containing provider-specific credentials
    sms_provider_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    email_from_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # HMAC signing key for outbound webhooks (stored encrypted)
    webhook_secret_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    max_notifications_per_day: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Per-tenant monthly cap on AI spend in USD. ``0.0`` means
    # "unlimited" (no enforcement). Set from the AI Admin → Usage tab
    # via ``PATCH /api/v1/ai-usage/budget``. Migration 015 added the
    # column; before it landed the setter silently dropped the value
    # because SQLAlchemy didn't know about the attribute.
    monthly_ai_budget_usd: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", nullable=False
    )
    # Per-tenant PII masking policy on AI egress: 'off' | 'detect-only' |
    # 'enforce' | 'strict'. NULL means "not explicitly set" → the effective
    # policy falls back to SMART_LLM_PII_DEFAULT_POLICY (default 'enforce'), so
    # masking is on out-of-the-box. A company admin sets an explicit value to
    # relax (or tighten) it. ``pii_categories`` optionally restricts which PII
    # types are masked (NULL = all). Migration 028.
    pii_masking_policy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pii_categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)


# ── Pydantic Schemas ──────────────────────────────────────────────────────────


class CompanySettingsCreate(BaseModel):
    company_id: uuid.UUID
    default_language: str = "en"
    sms_provider: str = "twilio"
    email_from_address: EmailStr | None = None
    email_from_name: str | None = None
    max_notifications_per_day: int = 10000

    @field_validator("sms_provider")
    @classmethod
    def validate_sms_provider(cls, v: str) -> str:
        if v not in ("twilio", "aws_sns"):
            raise ValueError("sms_provider must be 'twilio' or 'aws_sns'")
        return v

    @field_validator("default_language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        if v not in ("en", "es", "fr"):
            raise ValueError("default_language must be one of: en, es, fr")
        return v


_PII_POLICIES = ("off", "detect-only", "enforce", "strict")


class CompanySettingsUpdate(BaseModel):
    default_language: str | None = None
    sms_provider: str | None = None
    email_from_address: EmailStr | None = None
    email_from_name: str | None = None
    max_notifications_per_day: int | None = None
    is_active: bool | None = None
    # PII masking on AI egress. None leaves the value unchanged; set explicitly
    # to relax/tighten from the platform default. See docs/pii-masking-compliance.
    pii_masking_policy: str | None = None
    pii_categories: list[str] | None = None

    @field_validator("sms_provider")
    @classmethod
    def validate_sms_provider(cls, v: str | None) -> str | None:
        if v is not None and v not in ("twilio", "aws_sns"):
            raise ValueError("sms_provider must be 'twilio' or 'aws_sns'")
        return v

    @field_validator("pii_masking_policy")
    @classmethod
    def validate_pii_policy(cls, v: str | None) -> str | None:
        if v is not None and v not in _PII_POLICIES:
            raise ValueError(f"pii_masking_policy must be one of: {', '.join(_PII_POLICIES)}")
        return v


class CompanySettingsPublic(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    default_language: str
    sms_provider: str
    email_from_address: str | None = None
    email_from_name: str | None = None
    max_notifications_per_day: int
    is_active: bool
    pii_masking_policy: str | None = None
    pii_categories: list[str] | None = None
    # NOTE: sms_provider_config and webhook_secret_key are NEVER returned via API

    model_config = {"from_attributes": True}
