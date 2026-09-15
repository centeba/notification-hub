"""Field-encryption-key rotation for integration-hub (SB-08).

integration-hub encrypts several columns with a **direct** key (no data key /
envelope — see ``core.security.encrypt_field``): the value is AES-256-GCM'd
straight under a key derived from ``FIELD_ENCRYPTION_KEY``, stored as
``base64(nonce || ciphertext)``. Rotating that key therefore fully decrypts every
value with the old key and re-encrypts with the new one — there is no wrapped DEK
to cheaply re-wrap, and every column shares the one key, so they must all rotate
together.

The encrypted values live in two shapes:
- **plain Text columns** — ``integration_credentials.encrypted_data``,
  ``notification_delivery_logs.recipient_contact``,
  ``notification_system_integrations.encrypted_config``;
- **JSON ``{"encrypted": <blob>}`` nests** —
  ``notification_company_settings.sms_provider_config``,
  ``notification_webhook_endpoints.headers`` / ``.auth_config``.

The sweep reads/writes the raw values through plain views of each table (not the
ORM) and takes both keys explicitly. Resumable via trial-decrypt, since no key
version is recorded.
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import JSON, Column, MetaData, Table, Text, Uuid, select, update
from sqlalchemy.ext.asyncio import AsyncSession

# (table, column) — value is a plain base64(nonce||ct) string.
_TEXT_TARGETS: tuple[tuple[str, str], ...] = (
    ("integration_credentials", "encrypted_data"),
    ("notification_delivery_logs", "recipient_contact"),
    ("notification_system_integrations", "encrypted_config"),
)
# (table, column) — value is a JSON object {"encrypted": <blob>}.
_JSON_TARGETS: tuple[tuple[str, str], ...] = (
    ("notification_company_settings", "sms_provider_config"),
    ("notification_webhook_endpoints", "headers"),
    ("notification_webhook_endpoints", "auth_config"),
)


def derive_key(field_encryption_key: str) -> bytes:
    """Derive the 32-byte AES key from a ``FIELD_ENCRYPTION_KEY`` — matches
    ``core.security._get_encryption_key`` so old/new keys derive identically."""
    return hashlib.sha256(field_encryption_key.encode()).digest()


def _decrypt(blob: str, key: bytes) -> str:
    raw = base64.b64decode(blob)
    return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()


def _encrypt(plaintext: str, key: bytes) -> str:
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plaintext.encode(), None)).decode()


def rewrap_field(blob: str, *, old_key: bytes, new_key: bytes) -> str:
    """Decrypt a ``base64(nonce||ct)`` field with ``old_key`` and re-encrypt it
    under ``new_key`` with a fresh nonce."""
    return _encrypt(_decrypt(blob, old_key), new_key)


def _rotate_blob(blob: str, *, old_key: bytes, new_key: bytes) -> str | None:
    """Return the re-encrypted blob, or ``None`` if it's already on the new key
    (resumability). Raises if it decrypts under neither key."""
    try:
        return rewrap_field(blob, old_key=old_key, new_key=new_key)
    except Exception:
        try:
            _decrypt(blob, new_key)
        except Exception as verify_exc:
            raise ValueError(
                "field decrypts under neither the old nor the new key (corruption)"
            ) from verify_exc
        return None  # already rotated under the new key


def _text_table(table_name: str, column: str) -> Table:
    return Table(
        table_name,
        MetaData(),
        Column("id", Uuid, primary_key=True),
        Column(column, Text),
    )


def _json_table(table_name: str, column: str) -> Table:
    return Table(
        table_name,
        MetaData(),
        Column("id", Uuid, primary_key=True),
        Column(column, JSON),
    )


async def _rewrap_text_column(
    session: AsyncSession, table_name: str, column: str, old_key: bytes, new_key: bytes
) -> int:
    table = _text_table(table_name, column)
    col = table.c[column]
    rows = (await session.execute(select(table).where(col.isnot(None)))).mappings().all()
    changed = 0
    for row in rows:
        blob = row[column]
        if not isinstance(blob, str) or not blob:
            continue
        new_blob = _rotate_blob(blob, old_key=old_key, new_key=new_key)
        if new_blob is not None:
            await session.execute(
                update(table).where(table.c.id == row["id"]).values({column: new_blob})
            )
            changed += 1
    return changed


async def _rewrap_json_column(
    session: AsyncSession, table_name: str, column: str, old_key: bytes, new_key: bytes
) -> int:
    table = _json_table(table_name, column)
    col = table.c[column]
    rows = (await session.execute(select(table).where(col.isnot(None)))).mappings().all()
    changed = 0
    for row in rows:
        value = row[column]
        if not (isinstance(value, dict) and isinstance(value.get("encrypted"), str)):
            continue  # not a {"encrypted": <blob>} nest — leave it
        new_blob = _rotate_blob(value["encrypted"], old_key=old_key, new_key=new_key)
        if new_blob is not None:
            await session.execute(
                update(table)
                .where(table.c.id == row["id"])
                .values({column: {**value, "encrypted": new_blob}})
            )
            changed += 1
    return changed


async def rewrap_all_fields(
    session: AsyncSession, *, old_key: bytes, new_key: bytes
) -> dict[str, int]:
    """Re-encrypt EVERY ``FIELD_ENCRYPTION_KEY`` column from the old key to the new
    one — the three Text columns and the three JSON ``{"encrypted": …}`` nests.
    Returns per-column counts. Resumable (already-rotated rows are skipped)."""
    counts: dict[str, int] = {}
    for table_name, column in _TEXT_TARGETS:
        counts[f"{table_name}.{column}"] = await _rewrap_text_column(
            session, table_name, column, old_key, new_key
        )
    for table_name, column in _JSON_TARGETS:
        counts[f"{table_name}.{column}"] = await _rewrap_json_column(
            session, table_name, column, old_key, new_key
        )
    await session.commit()
    return counts
