"""AES-GCM credential encryption at rest.

The key is a base64-encoded 32-byte value supplied through
CREDENTIAL_ENCRYPTION_KEY, which must live outside source
control. A previous key may be supplied through
CREDENTIAL_ENCRYPTION_KEY_PREVIOUS so credentials can be
re-encrypted during rotation. Plaintext secrets are never
stored, never returned by read APIs, and never logged:
read APIs return only a masked suffix (at most the last
four characters). Decryption happens only in authorised
internal service paths, such as the integration
test-connection path.
"""

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


class CredentialEncryptionError(Exception):
    """Raised for missing, invalid, or undecryptable keys."""


def _decode_key(value: str | None, label: str) -> bytes:
    if not value:
        raise CredentialEncryptionError(f"Credential encryption key is not configured ({label})")
    try:
        key = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise CredentialEncryptionError(
            f"Credential encryption key is not valid base64 ({label})"
        ) from exc
    if len(key) != 32:
        raise CredentialEncryptionError(
            f"Credential encryption key must decode to 32 bytes ({label})"
        )
    return key


def _key_for(key_id: str) -> bytes:
    """Resolve a stored key id to its key material.

    Stable version ids (settings.credential_encryption_key_id
    and ..._previous_id) are used for rows written since
    Phase 9. The legacy ids "current" and "previous" are
    honoured for older rows. Any other id is an error:
    silently falling back to the current key would mask
    corrupt or rotated rows (Phase 9 audit).
    """
    if key_id == settings.credential_encryption_key_id:
        return _decode_key(settings.credential_encryption_key, key_id)
    if (
        settings.credential_encryption_key_previous_id is not None
        and key_id == settings.credential_encryption_key_previous_id
    ):
        return _decode_key(settings.credential_encryption_key_previous, key_id)
    if key_id == "current":
        return _decode_key(settings.credential_encryption_key, "current")
    if key_id == "previous":
        return _decode_key(settings.credential_encryption_key_previous, "previous")
    raise CredentialEncryptionError(f"Unknown credential encryption key id: {key_id}")


def require_encryption_key() -> None:
    """Fail clearly when credential writes cannot be encrypted.

    Production startup already fails without a key (see the
    settings validator); this guard gives the same clear
    failure for credential writes in any environment.
    """
    _decode_key(settings.credential_encryption_key, "current")


def encrypt_secret(plaintext: str) -> dict:
    """Encrypt a secret. Returns ciphertext, nonce, and key id.

    The nonce is fresh for every encryption, so identical
    plaintexts never produce identical ciphertexts.
    """
    key = _decode_key(settings.credential_encryption_key, "current")
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return {
        "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
        "nonce_b64": base64.b64encode(nonce).decode("ascii"),
        # Stable version id, not the literal "current":
        # after rotation this row must still decrypt via
        # the previous key, which is only possible if the
        # id it was written under is preserved.
        "key_id": settings.credential_encryption_key_id,
    }


def decrypt_secret(ciphertext_b64: str, nonce_b64: str, key_id: str) -> str:
    try:
        ciphertext = base64.b64decode(ciphertext_b64, validate=True)
        nonce = base64.b64decode(nonce_b64, validate=True)
    except Exception as exc:
        raise CredentialEncryptionError("Stored credential is not valid base64") from exc
    try:
        plaintext = AESGCM(_key_for(key_id)).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise CredentialEncryptionError("Stored credential could not be decrypted") from exc
    except CredentialEncryptionError:
        raise
    except Exception as exc:
        raise CredentialEncryptionError("Stored credential could not be decrypted") from exc
    return plaintext.decode("utf-8")


def mask_secret(value: str | None) -> str | None:
    """Mask a credential for display: at most the last four characters."""
    if not value:
        return None
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]
