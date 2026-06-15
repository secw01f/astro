import json
import os
import pathlib

CONFIG_DIR = pathlib.Path.home() / ".astro"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_URL = "http://localhost:8000"

def default_config() -> dict:
    return {"token": None, "url": DEFAULT_URL}

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return default_config()
    with open(CONFIG_FILE) as f:
        data = json.load(f)
    if not data.get("url"):
        data["url"] = DEFAULT_URL
    return data

def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(CONFIG_DIR, 0o700)
    fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(config, f, indent=4)
    os.chmod(CONFIG_FILE, 0o600)

def ensure_config_file() -> dict:
    if CONFIG_FILE.exists():
        return load_config()
    config = default_config()
    save_config(config)
    return config

def set_url(url: str) -> None:
    config = ensure_config_file()
    config["url"] = url.rstrip("/")
    save_config(config)

def set_token(token: str | None) -> None:
    config = ensure_config_file()
    config["token"] = token
    save_config(config)

def resolve_runtime() -> tuple[str, str | None]:
    """Return API URL and token, with environment variables overriding the file."""
    config = load_config() if CONFIG_FILE.exists() else default_config()
    url = os.getenv("ASTRO_API_URL") or config.get("url") or DEFAULT_URL
    token = os.getenv("ASTRO_API_TOKEN")
    if token is None:
        token = config.get("token")
    return url.rstrip("/"), token

def mask_token(token: str | None) -> str:
    if not token:
        return "(not set)"
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}…{token[-4:]}"
