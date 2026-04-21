import base64

from cryptography.fernet import Fernet
from settings import settings

def get_encryption_key():
    secret = settings.SECRET_KEY.encode()
    key = base64.urlsafe_b64encode(secret[:32].ljust(32, b'0'))
    return Fernet(key)

def encrypt_token(token):
    f = get_encryption_key()
    return f.encrypt(token.encode()).decode()

def decrypt_token(encrypted_value):
    f = get_encryption_key()
    return f.decrypt(encrypted_value.encode()).decode()