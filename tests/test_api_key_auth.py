"""API-key generation/verification tests.

Ported from the retired standalone ``notification-api`` service. Covers the
crypto primitives behind ``X-API-Key`` auth (``get_api_key_context``).
"""

from __future__ import annotations

from integration_hub_backend.api.core.security import (
    generate_api_key,
    hash_api_key,
    verify_api_key,
)


def test_generate_api_key_returns_three_values():
    plaintext, prefix, key_hash = generate_api_key()
    assert plaintext and prefix and key_hash
    assert prefix == plaintext.split(".")[0]


def test_api_key_plaintext_format():
    plaintext, _, _ = generate_api_key()
    assert "." in plaintext  # prefix.secret


def test_api_key_verify_correct():
    plaintext, _, key_hash = generate_api_key()
    assert verify_api_key(plaintext, key_hash) is True


def test_api_key_verify_wrong_key():
    _, _, key_hash = generate_api_key()
    assert verify_api_key("totally-wrong.key", key_hash) is False


def test_api_key_verify_tampered_hash():
    plaintext, _, _ = generate_api_key()
    assert verify_api_key(plaintext, "notahash") is False


def test_api_key_each_generation_unique():
    a, _, _ = generate_api_key()
    b, _, _ = generate_api_key()
    assert a != b


def test_hash_api_key_is_deterministic_and_verifiable():
    plaintext, _, _ = generate_api_key()
    h = hash_api_key(plaintext)
    assert verify_api_key(plaintext, h) is True
