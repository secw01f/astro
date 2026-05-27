from lib.config import ensure_config_file, save_config


def persist_token(token: str):
    config = ensure_config_file()
    config["token"] = token
    save_config(config)
