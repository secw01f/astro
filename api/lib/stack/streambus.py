"""Redis-backed transport for interactive stack runs.

Interactive runs execute inside a Celery worker, so the in-process asyncio
queues used for streaming and file requests no longer work across process
boundaries. This module bridges the two directions:

- **events** (worker -> client): a Redis Stream per run carries the SSE payloads
  produced by ``execute_stack_run``. The API tails it and relays over SSE.
- **control** (client -> worker): a Redis list per run carries file-upload
  results and cancellation, which the worker applies to the run's file session.
- **meta**: a Redis hash per run records ownership so the file endpoint can
  authorize uploads without an in-process session.
"""
import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Optional

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from settings import settings

logger = logging.getLogger(__name__)

_STREAM_MAXLEN = 5000


def _require_redis_url() -> str:
    if not settings.REDIS_URL:
        raise RuntimeError("REDIS_URL must be configured for interactive stack runs")
    return settings.REDIS_URL


def _client() -> "aioredis.Redis":
    return aioredis.from_url(_require_redis_url(), decode_responses=True)


def _events_key(run_id: str) -> str:
    return f"astro:run:{run_id}:events"


def _control_key(run_id: str) -> str:
    return f"astro:run:{run_id}:control"


def _meta_key(run_id: str) -> str:
    return f"astro:run:{run_id}:meta"


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


class RedisEventPublisher:
    """Queue-compatible sink that forwards run events to a Redis stream.

    Exposes an async ``put`` so it can stand in for the in-process client queue
    that ``execute_stack_run`` writes to. ``put(None)`` marks end-of-stream.
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._key = _events_key(run_id)
        self._redis = _client()

    async def put(self, item: Optional[dict[str, Any]]) -> None:
        if item is None:
            await self._redis.xadd(
                self._key, {"eos": "1"}, maxlen=_STREAM_MAXLEN, approximate=True
            )
            await self._redis.expire(self._key, settings.RUN_STREAM_TTL_SECONDS)
            return
        await self._redis.xadd(
            self._key,
            {"data": json.dumps(item, default=str)},
            maxlen=_STREAM_MAXLEN,
            approximate=True,
        )

    async def emit_error(self, message: str) -> None:
        await self.put(
            {
                "type": "error",
                "run_id": self.run_id,
                "content": message,
                "timestamp": time.time(),
            }
        )

    async def aclose(self) -> None:
        await self._redis.aclose()


async def stream_run_events(
    run_id: str,
    is_disconnected: Callable[[], Awaitable[bool]],
):
    """Yield SSE lines for a run by tailing its Redis events stream.

    ``is_disconnected`` is awaited each poll (e.g. ``request.is_disconnected``)
    so relaying stops and the run is cancelled when the client goes away.
    """
    redis = _client()
    key = _events_key(run_id)
    last_id = "0-0"
    started = False
    deadline = time.monotonic() + settings.RUN_STREAM_STARTUP_TIMEOUT_SECONDS
    try:
        while True:
            if await is_disconnected():
                await _publish_control(run_id, {"kind": "cancel"})
                return

            entries = await redis.xread({key: last_id}, block=1000, count=100)
            if not entries:
                if not started and time.monotonic() > deadline:
                    yield _sse(
                        {
                            "type": "error",
                            "run_id": run_id,
                            "content": "Run did not start (no worker available).",
                        }
                    )
                    return
                continue

            for _stream_key, records in entries:
                for entry_id, fields in records:
                    last_id = entry_id
                    started = True
                    if fields.get("eos"):
                        return
                    data = fields.get("data")
                    if data:
                        yield f"data: {data}\n\n"
    finally:
        await redis.aclose()


async def set_run_meta(run_id: str, stack_id: int, user_id: int) -> None:
    redis = _client()
    try:
        await redis.hset(
            _meta_key(run_id), mapping={"stack_id": stack_id, "user_id": user_id}
        )
        await redis.expire(_meta_key(run_id), settings.RUN_STREAM_TTL_SECONDS)
    finally:
        await redis.aclose()


async def get_run_meta(run_id: str) -> dict[str, int] | None:
    redis = _client()
    try:
        meta = await redis.hgetall(_meta_key(run_id))
    finally:
        await redis.aclose()
    if not meta:
        return None
    try:
        return {"stack_id": int(meta["stack_id"]), "user_id": int(meta["user_id"])}
    except (KeyError, ValueError):
        return None


async def _publish_control(run_id: str, message: dict[str, Any]) -> None:
    redis = _client()
    try:
        await redis.rpush(_control_key(run_id), json.dumps(message))
        await redis.expire(_control_key(run_id), settings.RUN_STREAM_TTL_SECONDS)
    finally:
        await redis.aclose()


async def publish_file_result(
    run_id: str, request_id: str, payload: dict[str, Any]
) -> None:
    await _publish_control(
        run_id, {"kind": "file", "request_id": request_id, "payload": payload}
    )


async def consume_control(run_id: str, file_session) -> None:
    """Worker-side loop applying control messages to the run's file session.

    This must stay alive for the entire run: if it dies while the agent is
    paused in ``file_request``, a later upload lands on the control list with no
    consumer, the pending future never resolves, and the run hangs forever.

    ``blpop`` races its server-side timeout against the client socket read
    timeout, so a quiet window (no upload for a few seconds) surfaces as a
    ``redis.TimeoutError``. That, and transient connection drops, are expected
    and must not tear the loop down.
    """
    redis = _client()
    key = _control_key(run_id)
    try:
        while True:
            try:
                res = await redis.blpop(key, timeout=5)
            except asyncio.CancelledError:
                raise
            except RedisError as exc:
                logger.debug("control blpop transient error for %s: %s", run_id, exc)
                await asyncio.sleep(0.1)
                continue
            if res is None:
                continue
            try:
                message = json.loads(res[1])
            except (json.JSONDecodeError, TypeError):
                continue
            kind = message.get("kind")
            if kind == "file":
                request_id = message.get("request_id")
                payload = message.get("payload") or {}
                if request_id:
                    file_session.resolve(request_id, payload)
            elif kind == "cancel":
                file_session.cancel_pending()
    except asyncio.CancelledError:
        raise
    finally:
        await redis.aclose()
