import json

import pytest

from integration_hub_backend.api.core.security import decrypt_field, encrypt_field


def test_encryption_decryption():
    """Verify that sensitive fields are encrypted and decrypted correctly using AES-256-GCM."""
    data = {"secret": "super-secret-key-123", "url": "https://api.datadoghq.com"}
    json_data = json.dumps(data)

    # Encrypt
    encrypted = encrypt_field(json_data)
    assert encrypted != json_data

    # Decrypt
    decrypted = decrypt_field(encrypted)
    assert decrypted == json_data

    # Parse and verify content
    decrypted_dict = json.loads(decrypted)
    assert decrypted_dict["secret"] == "super-secret-key-123"
    assert decrypted_dict["url"] == "https://api.datadoghq.com"


def test_decryption_failure():
    """Verify that decryption fails gracefully with invalid input."""
    with pytest.raises(Exception):
        decrypt_field("invalid-encrypted-blob")
