import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from settings import settings

def get_encryption_key():
    secret = settings.CREDENTIAL_ENCRYPTION_KEY.encode()
    raw_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"astro-credential-encryption-v1",
    ).derive(secret)
    key = base64.urlsafe_b64encode(raw_key)
    return Fernet(key)

def encrypt_token(token):
    f = get_encryption_key()
    return f.encrypt(token.encode()).decode()

def decrypt_token(encrypted_value):
    f = get_encryption_key()
    return f.decrypt(encrypted_value.encode()).decode()
