import hashlib
from collections.abc import Hashable
from functools import cache
from typing import Any
from typing import cast

from pydantic import BaseModel
from pydantic import TypeAdapter


@cache
def _adapter(shape: Hashable) -> TypeAdapter[Any]:
    return TypeAdapter(shape)


def adapter[T](shape: type[T]) -> TypeAdapter[T]:
    return _adapter(cast(Hashable, shape))


def params_key(prefix: str, params: BaseModel | None = None) -> str:
    if params is None:
        return prefix

    digest = hashlib.blake2b(params.model_dump_json().encode(), digest_size=8)

    return f"{prefix}:{digest.hexdigest()}"
