"""Pytest configuration and shared fixtures."""

import os

# The hub no longer mints a random JWT secret when none is configured (an unset
# key must fail closed, not verify against a value no issuer holds). Tests that
# mint tokens read settings.SECRET_KEY, so give them one before config loads.
os.environ.setdefault("SECRET_KEY", "test-only-jwt-secret-not-for-deployment")

from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler


def _visit_JSONB(self, type_, **kw):
    """Render JSONB as plain JSON text for SQLite (used in tests only)."""
    return "JSON"


# Patch SQLite compiler so models using JSONB work with in-memory SQLite test DBs
SQLiteTypeCompiler.visit_JSONB = _visit_JSONB
