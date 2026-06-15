from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def map_ordered(items: Iterable[T], fn: Callable[[T], R], *, max_workers: int = 1) -> list[R]:
    values = list(items)
    if max_workers <= 1:
        return [fn(item) for item in values]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fn, item) for item in values]
        return [future.result() for future in futures]
