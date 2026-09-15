"""Security utilities: API key generation/hashing, JWT validation, field encryption."""

import base64
import hashlib
import hmac
import os
import secrets
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pwdlib import PasswordHash
from smart_llm.platform_auth import decode_platform_token

from integration_hub_backend.api.core.config import settings

_password_hash = PasswordHash.recommended()

# ── API Key management ────────────────────────────────────────────────────────

API_KEY_PREFIX_LEN = 8
API_KEY_TOTAL_LEN = 40  # prefix (8) + separator (1) + secret (31)


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.
    Returns (plaintext_key, key_prefix, key_hash).
    plaintext_key is shown ONCE to the user — never stored.
    key_hash is stored in DB via bcrypt.
    key_prefix is stored in DB for display (e.g. "ihk_abc12...").
    """
    raw = secrets.token_urlsafe(32)
    prefix = f"ihk_{raw[:API_KEY_PREFIX_LEN]}"
    plaintext = f"{prefix}.{raw}"
    key_hash = hash_api_key(plaintext)
    return plaintext, prefix, key_hash


def hash_api_key(plaintext: str) -> str:
    return _password_hash.hash(plaintext)


def verify_api_key(plaintext: str, hashed: str) -> bool:
    try:
        return _password_hash.verify(plaintext, hashed)
    except Exception:
        return False


# ── JWT validation (tokens issued by User Master) ────────────────────────────


def decode_user_master_token(token: str) -> dict[str, Any]:
    """
    Validate a JWT issued by User Master.
    Raises jwt.InvalidTokenError on failure.
    """
    claims: dict[str, Any] = decode_platform_token(
        token, settings.SECRET_KEY, require=["sub", "exp"]
    )
    return claims


# ── AES-256-GCM field-level encryption for PII (phone, webhook secrets) ──────


def _get_encryption_key() -> bytes:
    """Derive a 32-byte AES key from the configured FIELD_ENCRYPTION_KEY.

    SEC H5 — never derive the key from an empty string: ``SHA256("")`` is a
    world-known constant, so an unset FIELD_ENCRYPTION_KEY would make all
    PII/webhook-secret ciphertext trivially decryptable. In production the
    config validator refuses to boot when it's unset; as a belt-and-braces
    fallback (and for dev/test where the field is often blank) we derive from
    SECRET_KEY instead of an empty seed, and refuse outright if neither is set.
    """
    seed = settings.FIELD_ENCRYPTION_KEY or settings.SECRET_KEY
    if not seed:
        raise RuntimeError(
            "field encryption unavailable: neither FIELD_ENCRYPTION_KEY nor "
            "SECRET_KEY is configured"
        )
    # Accept base64-encoded or raw; always produce exactly 32 bytes via SHA-256.
    return hashlib.sha256(seed.encode()).digest()


def encrypt_field(plaintext: str) -> str:
    """Encrypt a plaintext string → base64-encoded ciphertext (nonce || ciphertext)."""
    if not plaintext:
        return plaintext
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_field(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext produced by encrypt_field()."""
    if not ciphertext:
        return ciphertext
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(ciphertext)
    nonce, ct = raw[:12], raw[12:]
    return aesgcm.decrypt(nonce, ct, None).decode()


# ── HMAC webhook signing ──────────────────────────────────────────────────────


def sign_webhook_payload(payload: bytes, secret: str) -> str:
    """Produce X-Hub-Signature-256 value for outbound webhooks."""
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def verify_webhook_signature(
    payload: bytes,
    secret: str,
    header: str,
    *,
    timestamp: str | None = None,
    max_age_seconds: int = 300,
) -> bool:
    """Verify an inbound webhook signature (constant-time).

    M1 — when ``timestamp`` is supplied, use the SDK's replay-protected scheme
    (HMAC over ``"{ts}.{body}"`` plus a freshness window), so a captured request
    can't be replayed later. Falls back to the body-only HMAC when no timestamp
    is present — required for third-party senders (e.g. GitHub) that don't sign
    a timestamp.
    """
    if timestamp is not None:
        try:
            from integration_hub_backend._platform.webhooks import verify_webhook

            verify_webhook(
                payload,
                signature_header=header,
                timestamp_header=timestamp,
                secret=secret,
                max_age_seconds=max_age_seconds,
            )
            return True
        except Exception:  # noqa: BLE001 — any verification failure → reject
            return False
    expected = sign_webhook_payload(payload, secret)
    return hmac.compare_digest(expected, header)
