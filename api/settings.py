from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_URL: str
    SECRET_KEY: str
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

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

settings = Settings()