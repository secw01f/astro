import logging
import json
import os

class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)

def log_config():
    log_path = "/var/log/astro/astro.log"
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    stream_handler = logging.StreamHandler()
    file_handler = logging.FileHandler(log_path)

    formatter = JsonFormatter()
    stream_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [stream_handler, file_handler]