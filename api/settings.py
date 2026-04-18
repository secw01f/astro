from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_URL: str
    SECRET_KEY: str
    DEFAULT_TOOLS_BASE_URL: str
    DEFAULT_EXP_MINUTES: int
    ENV: str
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

settings = Settings()