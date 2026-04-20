import pathlib
import json

def persist_token(token: str):
    _config_file = pathlib.Path.home() / ".astro" / "config.json"
    with open(_config_file, "r") as f:
        _config = json.load(f)
    _config["token"] = token
    with open(_config_file, "w") as f:
        json.dump(_config, f, indent=4)