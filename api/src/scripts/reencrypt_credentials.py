"""Re-encrypt stored credentials from one Fernet key to another.

Use this when rotating ``CREDENTIAL_ENCRYPTION_KEY``. Point ``--old-key`` at the
key the credentials are currently encrypted with; ``--new-key`` defaults to the
value configured in the environment (``CREDENTIAL_ENCRYPTION_KEY``).

    python -m src.scripts.reencrypt_credentials --old-key <OLD_FERNET_KEY>

The operation is idempotent per credential: any row that already decrypts with
the new key is left untouched, so re-running after a partial failure is safe.
"""

import argparse
import asyncio
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlmodel import select

from settings import settings
from src.db.db import async_session
from src.db.models import Credential

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reencrypt_credentials")


async def reencrypt(old_key: str, new_key: str) -> tuple[int, int]:
    old = Fernet(old_key.encode())
    new = Fernet(new_key.encode())

    migrated = 0
    skipped = 0

    async with async_session() as session:
        credentials = (await session.exec(select(Credential))).all()
        for credential in credentials:
            token = credential.token.encode()
            try:
                new.decrypt(token)
                skipped += 1
                continue
            except InvalidToken:
                pass

            plaintext = old.decrypt(token)
            credential.token = new.encrypt(plaintext).decode()
            session.add(credential)
            migrated += 1

        await session.commit()

    return migrated, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-encrypt credentials to a new Fernet key")
    parser.add_argument("--old-key", required=True, help="Current Fernet key the credentials use")
    parser.add_argument(
        "--new-key",
        default=settings.CREDENTIAL_ENCRYPTION_KEY,
        help="Target Fernet key (defaults to CREDENTIAL_ENCRYPTION_KEY)",
    )
    args = parser.parse_args()

    migrated, skipped = asyncio.run(reencrypt(args.old_key, args.new_key))
    logger.info("Re-encrypted %s credential(s); %s already current", migrated, skipped)


if __name__ == "__main__":
    main()
