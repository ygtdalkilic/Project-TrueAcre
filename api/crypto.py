"""Application-level encryption for uploaded company data.

Every uploaded table is encrypted with AES-256-GCM before it reaches the database and decrypted
only in memory when a company's scores are computed. A database leak on its own therefore exposes
no grower data: the key lives in Secret Manager (DATA_ENCRYPTION_KEY), never in the database or
the repository. GCM also authenticates the data, so tampering is detected on read.

Configuration:
  DATA_ENCRYPTION_KEY  urlsafe-base64 of 32 random bytes (make one with `python -m api.crypto`);
                       required in production, derived from SESSION_SECRET in development
"""
import base64
import hashlib
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from api.security import IS_PRODUCTION

NONCE_BYTES = 12  # AES-GCM standard nonce size; a fresh random nonce per encryption


def generate_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def _load_key() -> bytes:
    raw = os.environ.get("DATA_ENCRYPTION_KEY")
    if raw:
        key = base64.urlsafe_b64decode(raw)
        if len(key) != 32:
            raise RuntimeError("DATA_ENCRYPTION_KEY must decode to exactly 32 bytes")
        return key
    if IS_PRODUCTION:
        raise RuntimeError("DATA_ENCRYPTION_KEY must be set in production")
    # Development: stable while SESSION_SECRET is stable, so a local database survives restarts.
    return hashlib.sha256((os.environ.get("SESSION_SECRET") or secrets.token_urlsafe(32)).encode()).digest()


KEY = _load_key()


def encrypt(text: str) -> bytes:
    nonce = secrets.token_bytes(NONCE_BYTES)
    return nonce + AESGCM(KEY).encrypt(nonce, text.encode("utf-8"), None)


def decrypt(blob: bytes) -> str:
    """Raises cryptography.exceptions.InvalidTag if the data was altered or the key is wrong."""
    return AESGCM(KEY).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], None).decode("utf-8")


if __name__ == "__main__":
    print(generate_key())
