import abc
from typing import Any, Awaitable, Callable


OnFrame = Callable[[bytes, str, Any], Awaitable[None]]  # (data, remote_id, ctx)


class AbstractTransport(abc.ABC):
    @abc.abstractmethod
    def set_on_frame(self, callback: OnFrame) -> None:
        ...

    @abc.abstractmethod
    async def start(self) -> None:
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        ...

    @abc.abstractmethod
    async def send(self, addr: str, data: bytes) -> None:
        ...

    @abc.abstractmethod
    async def send_via_context(self, ctx: Any, data: bytes) -> None:
        ...

    async def connect_seed(self, seed: str) -> None:
        return None

