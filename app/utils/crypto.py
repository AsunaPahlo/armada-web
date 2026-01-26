"""
Encryption utilities for sensitive data storage.
Uses Fernet symmetric encryption with a key derived from SECRET_KEY.
"""
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _get_fernet() -> Fernet:
    """Get Fernet instance using key derived from SECRET_KEY."""
    secret_key = current_app.config['SECRET_KEY']
    # Derive a 32-byte key from SECRET_KEY using SHA256
    key = hashlib.sha256(secret_key.encode()).digest()
    # Fernet requires base64-encoded 32-byte key
    fernet_key = base64.urlsafe_b64encode(key)
    return Fernet(fernet_key)


def encrypt_value(plaintext: str) -> str:
    """
    Encrypt a string value for database storage.
    Returns base64-encoded encrypted string.
    """
    if not plaintext:
        return None
    fernet = _get_fernet()
    encrypted = fernet.encrypt(plaintext.encode())
    return encrypted.decode()


def decrypt_value(encrypted: str) -> str:
    """
    Decrypt a stored encrypted value.
    Returns original plaintext string.
    """
    if not encrypted:
        return None
    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(encrypted.encode())
        return decrypted.decode()
    except InvalidToken:
        # Return None if decryption fails (wrong key or corrupted data)
        # This handles the case where data was stored before encryption was added
        return encrypted  # Return as-is for backward compatibility
