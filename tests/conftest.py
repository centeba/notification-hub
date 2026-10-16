"""Pytest configuration and shared fixtures."""

import base64
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# user-master signs RS256: tests sign with JWT_KEY and the hub verifies with its
# public half, as it verifies user-master's keys from JWKS in a deployment.
JWT_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
os.environ.setdefault(
    "JWT_PUBLIC_KEY",
    JWT_KEY.public_key()
    .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    .decode(),
)
# The hub's encryption keys no longer fall back to a JWT secret.
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "test-only-field-encryption-key")
os.environ.setdefault("LLM_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"t" * 32).decode())

from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler


def _visit_JSONB(self, type_, **kw):
    """Render JSONB as plain JSON text for SQLite (used in tests only)."""
    return "JSON"


# Patch SQLite compiler so models using JSONB work with in-memory SQLite test DBs
SQLiteTypeCompiler.visit_JSONB = _visit_JSONB
