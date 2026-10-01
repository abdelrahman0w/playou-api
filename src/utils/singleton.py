from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from contextlib import asynccontextmanager
from typing import Any
from typing import ClassVar


class Singleton[T]:
    _instance: ClassVar[Any] = None

    @classmethod
    def create(cls) -> T:
        raise NotImplementedError

    @classmethod
    async def connect(cls, instance: T) -> None: ...

    @classmethod
    async def dispose(cls, instance: T) -> None: ...

    @classmethod
    def get(cls) -> T:
        instance = cls.__dict__.get("_instance")
        if instance is None:
            instance = cls.create()
            cls._instance = instance

        return instance

    @classmethod
    async def open(cls) -> T:
        instance = cls.get()
        await cls.connect(instance)

        return instance

    @classmethod
    async def close(cls) -> None:
        instance = cls.__dict__.get("_instance")
        cls._instance = None

        if instance is not None:
            await cls.dispose(instance)


@asynccontextmanager
async def connect_singletons(
    *singletons: type[Singleton[Any]],
) -> AsyncGenerator[None]:
    async with AsyncExitStack() as stack:
        for singleton in singletons:
            stack.push_async_callback(singleton.close)
            await singleton.open()

        yield
