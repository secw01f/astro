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
