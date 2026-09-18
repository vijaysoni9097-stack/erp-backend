"""Password and PIN hashing utilities."""

from base64 import b64decode, b64encode
from hashlib import scrypt
from hmac import compare_digest
from os import urandom


def hash_secret(value: str) -> str:
    """Return a salted scrypt hash; plain-text secrets are never stored."""
    salt = urandom(16)
    digest = scrypt(value.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt$16384${b64encode(salt).decode()}${b64encode(digest).decode()}"


def verify_secret(value: str, encoded_secret: str) -> bool:
    """Safely verify a supplied secret against an encoded scrypt hash."""
    try:
        algorithm, work_factor, encoded_salt, encoded_digest = encoded_secret.split("$")
        if algorithm != "scrypt":
            return False
        expected = scrypt(value.encode(), salt=b64decode(encoded_salt), n=int(work_factor), r=8, p=1)
        return compare_digest(expected, b64decode(encoded_digest))
    except (ValueError, TypeError):
        return False
