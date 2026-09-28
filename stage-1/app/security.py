"""Password hashing (salted scrypt) and bearer tokens.

Stored password format: `scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>`. The parameters are
stored with each hash, so the cost can change without breaking existing accounts.
Tokens are random; only their SHA-256 digest is stored.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

# N=2^13, r=8 costs ~16 ms and 8 MiB per hash on one core; hashlib.scrypt releases the
# GIL, so hashes run in parallel across the 2 vCPU. That keeps a 200-user reset well
# under 10 s and 50 concurrent logins well under 5 s (D12, D21).
SCRYPT_N = 2 ** 13
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 64 * 1024 * 1024
SALT_BYTES = 16
KEY_BYTES = 32

# Bounds memory and CPU contention when many logins arrive at once.
_HASH_SLOTS = threading.BoundedSemaphore(max(2, 2 * (os.cpu_count() or 1)))
_BULK_WORKERS = max(2, os.cpu_count() or 1)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    with _HASH_SLOTS:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                              maxmem=SCRYPT_MAXMEM, dklen=KEY_BYTES)


def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def hash_passwords(passwords: Iterable[str]) -> list[str]:
    """Hash many passwords in parallel, in order."""
    with ThreadPoolExecutor(max_workers=_BULK_WORKERS) as pool:
        return list(pool.map(hash_password, passwords))


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, base64.b64decode(digest))


# Checked against when the email is unknown, so both failures cost the same time.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
