from __future__ import annotations

from contextvars import ContextVar

_user_id: ContextVar[int | None] = ContextVar("user_id", default=None)


def set_user_id(user_id: int | None) -> object:
    return _user_id.set(user_id)


def reset_user_id(token: object) -> None:
    _user_id.reset(token)


def get_user_id() -> int | None:
    return _user_id.get()


def require_user_id() -> int | None:
    return _user_id.get()
