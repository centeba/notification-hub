"""Pytest configuration and shared fixtures."""

from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler


def _visit_JSONB(self, type_, **kw):
    """Render JSONB as plain JSON text for SQLite (used in tests only)."""
    return "JSON"


# Patch SQLite compiler so models using JSONB work with in-memory SQLite test DBs
SQLiteTypeCompiler.visit_JSONB = _visit_JSONB
