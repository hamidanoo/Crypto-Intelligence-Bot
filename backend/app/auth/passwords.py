"""Argon2id password hashing.

Argon2id is the required algorithm for Phase 8. The
parameters come from settings and are documented in
docs/CREDENTIAL_ENCRYPTION.md and docs/ADMIN_SETUP.md;
defaults are time_cost=3, memory_cost=64 MiB,
parallelism=4. Passwords are never logged, and hashes are
never returned by any API response.
"""

from argon2 import PasswordHasher, exceptions

from app.config import settings


def _hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost_kib,
        parallelism=settings.argon2_parallelism,
        hash_len=32,
        salt_len=16,
    )


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher().verify(password_hash, password)
    except (exceptions.VerifyMismatchError, exceptions.InvalidHashError):
        return False
    except Exception:
        return False
