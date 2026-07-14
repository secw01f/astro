"""Symmetric encryption for stored third-party credentials.

Credential encryption is intentionally decoupled from ``SECRET_KEY`` (which
signs JWTs) so that rotating the JWT key never invalidates stored credentials.
``CREDENTIAL_ENCRYPTION_KEY`` must be a valid Fernet key; generate one with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

To rotate the credential key, run ``python -m src.scripts.reencrypt_credentials``.
"""

from functools import lru_cache

from cryptography.fernet import Fernet

from settings import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    try:
        return Fernet(settings.CREDENTIAL_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`"
        ) from exc


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(encrypted_value: str) -> str:
    return _fernet().decrypt(encrypted_value.encode()).decode()
