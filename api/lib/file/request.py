import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from settings import settings

_FILE_REQUEST_TIMEOUT_SECONDS = settings.FILE_REQUEST_TIMEOUT_SECONDS


@dataclass
class FileRunSession:
    run_id: str
    stack_id: int
    user_id: int
    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop
    agent_name: str = "stack"
    _pending: dict[str, asyncio.Future] = field(default_factory=dict)

    def _enqueue(self, item: dict[str, Any]) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self.queue.put_nowait(item)
        else:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, item)

    def emit_file_request(self, request_id: str, description: str) -> None:
        self._enqueue({
            "type": "file_request",
            "agent": self.agent_name,
            "run_id": self.run_id,
            "request_id": request_id,
            "description": description,
            "timestamp": time.time(),
        })

    def create_pending(self, request_id: str) -> asyncio.Future:
        fut = self.loop.create_future()
        self._pending[request_id] = fut
        return fut

    def resolve(self, request_id: str, result: dict[str, Any]) -> bool:
        fut = self._pending.pop(request_id, None)
        if fut is None or fut.done():
            return False
        self.loop.call_soon_threadsafe(fut.set_result, result)
        return True

    def cancel_pending(self) -> None:
        for request_id, fut in list(self._pending.items()):
            if not fut.done():
                self.loop.call_soon_threadsafe(
                    fut.set_exception,
                    asyncio.CancelledError(f"Run {self.run_id} ended"),
                )
        self._pending.clear()

    async def wait_for_file(
        self,
        request_id: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        fut = self._pending.get(request_id)
        if fut is None:
            raise KeyError(request_id)
        wait_timeout = (
            _FILE_REQUEST_TIMEOUT_SECONDS if timeout is None else timeout
        )
        return await asyncio.wait_for(fut, timeout=wait_timeout)


class FileRunRegistry:
    _sessions: dict[str, FileRunSession] = {}

    @classmethod
    def register(cls, session: FileRunSession) -> None:
        cls._sessions[session.run_id] = session

    @classmethod
    def get(cls, run_id: str) -> FileRunSession | None:
        return cls._sessions.get(run_id)

    @classmethod
    def unregister(cls, run_id: str) -> None:
        session = cls._sessions.pop(run_id, None)
        if session is not None:
            session.cancel_pending()
