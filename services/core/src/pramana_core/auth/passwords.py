"""Password hashing with the standard library's scrypt (RFC 7914).

Format: ``scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>``. Parameters are stored with each hash,
so they can be raised later without invalidating existing passwords. ``n = 2**14, r = 8,
p = 1`` is the OWASP Password Storage Cheat Sheet's scrypt floor and uses 16 MiB of memory.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

N, R, P = 2**14, 8, 1
KEY_LEN = 32
MAXMEM = 64 * 1024 * 1024
MIN_PASSWORD_LEN = 8


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"passwords need at least {MIN_PASSWORD_LEN} characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=N, r=R, p=P, dklen=KEY_LEN, maxmem=MAXMEM
    )
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time comparison; malformed hashes never verify."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(digest)
        actual = hashlib.scrypt(
            password.encode(),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# A hash of a random password, verified against when the email is unknown, so a failed
# sign-in takes the same time whether or not the account exists.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
