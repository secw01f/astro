from pydantic import model_validator
from pydantic_settings import BaseSettings


_WEAK_SECRET_VALUES = {
    "",
    "secret",
    "changeme",
    "change-me",
    "supersecretkey",
    "password",
}


def _validate_secret(name: str, value: str) -> None:
    normalized = value.strip()
    if normalized.lower() in _WEAK_SECRET_VALUES:
        raise ValueError(f"{name} must not use a known weak/default value")
    if len(normalized) < 32:
        raise ValueError(f"{name} must be at least 32 characters")

class Settings(BaseSettings):
    DB_URL: str
    JWT_SECRET_KEY: str
    JWT_ISSUER: str = "astro-api"
    JWT_AUDIENCE: str = "astro-api"
    CREDENTIAL_ENCRYPTION_KEY: str
    TOOLS_HMAC_SECRET: str
    DEFAULT_TOOLS_BASE_URL: str
    DEFAULT_EXP_MINUTES: int
    ENV: str
    REDIS_URL: str | None = None
    LLM_LIMITER_ENABLED: bool = False
    LLM_TOKEN_LIMIT_PER_MINUTE: int = 30000
    LLM_LIMITER_POLL_INTERVAL_MS: int = 200
    LLM_LIMITER_DEFAULT_OUTPUT_TOKENS: int = 1024
    LLM_PROMPT_CACHE_ENABLED: bool = False
    LLM_PROMPT_CACHE_TTL_SECONDS: int = 300
    MEMORY_RECALL_MAX_ITEMS: int = 5
    MEMORY_LIST_MAX_ITEMS: int = 10
    MEMORY_ITEM_MAX_CHARS: int = 400
    TOOL_OUTPUT_MAX_CHARS: int = 2000
    FILES_DIR: str = "/var/lib/astro/files"
    FILE_REQUEST_TIMEOUT_SECONDS: int = 3600
    STACK_RUN_MAX_CONCURRENCY: int = 4
    LLM_LIMITER_MAX_WAIT_SECONDS: int = 60
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024
    OUTBOUND_ALLOWLIST: str = ""
    CREDENTIAL_CRYPTO_VERSION: int = 2

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        secrets = {
            "JWT_SECRET_KEY": self.JWT_SECRET_KEY,
            "CREDENTIAL_ENCRYPTION_KEY": self.CREDENTIAL_ENCRYPTION_KEY,
            "TOOLS_HMAC_SECRET": self.TOOLS_HMAC_SECRET,
        }
        for name, value in secrets.items():
            _validate_secret(name, value)
        if len(set(secrets.values())) != len(secrets):
            raise ValueError("JWT_SECRET_KEY, CREDENTIAL_ENCRYPTION_KEY, and TOOLS_HMAC_SECRET must be distinct")
        if self.MAX_UPLOAD_BYTES <= 0:
            raise ValueError("MAX_UPLOAD_BYTES must be positive")
        if self.LLM_LIMITER_MAX_WAIT_SECONDS <= 0:
            raise ValueError("LLM_LIMITER_MAX_WAIT_SECONDS must be positive")
        return self

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

settings = Settings()
