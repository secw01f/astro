import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from settings import settings

_FILES_ROOT = Path(settings.FILES_DIR)


def _user_dir(user_id: int) -> Path:
    return _FILES_ROOT / str(user_id)


def _validate_file_id(file_id: str) -> str:
    try:
        return str(uuid.UUID(file_id))
    except ValueError as exc:
        raise ValueError("Invalid file_id") from exc


def _safe_user_path(user_id: int, filename: str) -> Path:
    root = _user_dir(user_id).resolve()
    path = (root / filename).resolve()
    if root != path.parent:
        raise ValueError("Invalid file path")
    return path


def _meta_path(user_id: int, file_id: str) -> Path:
    safe_id = _validate_file_id(file_id)
    return _safe_user_path(user_id, f"{safe_id}.json")


def _data_path(user_id: int, file_id: str) -> Path:
    safe_id = _validate_file_id(file_id)
    return _safe_user_path(user_id, f"{safe_id}.bin")


def save_user_file(
    user_id: int,
    filename: str,
    content: bytes,
    *,
    content_type: str | None = None,
) -> dict:
    file_id = str(uuid.uuid4())
    user_path = _user_dir(user_id)
    user_path.mkdir(parents=True, exist_ok=True)

    row = {
        "id": file_id,
        "filename": filename or "upload",
        "content_type": content_type or "application/octet-stream",
        "size": len(content),
        "created": datetime.now(timezone.utc).isoformat(),
    }
    _data_path(user_id, file_id).write_bytes(content)
    _meta_path(user_id, file_id).write_text(json.dumps(row))
    return row


def list_user_files(user_id: int) -> list[dict]:
    user_path = _user_dir(user_id)
    if not user_path.is_dir():
        return []

    rows: list[dict] = []
    for meta_file in sorted(user_path.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            rows.append(json.loads(meta_file.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return rows


def get_user_file(user_id: int, file_id: str) -> tuple[dict, bytes] | None:
    try:
        meta_path = _meta_path(user_id, file_id)
        data_path = _data_path(user_id, file_id)
    except ValueError:
        return None
    if not meta_path.is_file() or not data_path.is_file():
        return None
    try:
        row = json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    try:
        content = data_path.read_bytes()
    except OSError:
        return None
    return row, content
