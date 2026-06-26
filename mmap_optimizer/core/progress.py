"""User-facing progress reporting utilities."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, TypeVar

try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover - exercised when tqdm is not installed
    tqdm = None

T = TypeVar("T")


class ProgressReporter:
    """Small wrapper around print/tqdm for user-facing execution progress."""

    def __init__(self, enabled: bool = True) -> None:
        env_disabled = os.environ.get("MMAP_DISABLE_PROGRESS", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.enabled = enabled and not env_disabled

    def phase_start(self, title: str) -> None:
        self.write(f"\n{'=' * 60}\n{title} 开始\n{'=' * 60}")

    def phase_done(self, title: str, metrics: str | None = None) -> None:
        suffix = f"\n{metrics}" if metrics else ""
        self.write(f"{'=' * 60}\n{title} 完成{suffix}\n{'=' * 60}")

    def stage(self, message: str) -> None:
        self.write(message)

    def step(self, message: str) -> None:
        self.write(message)

    def write(self, message: str) -> None:
        if not self.enabled:
            return
        if tqdm is not None:
            tqdm.write(message)
        else:
            print(message)

    def iter(
        self,
        iterable: Iterable[T],
        *,
        desc: str,
        total: int | None = None,
        postfix: dict[str, Any] | None = None,
    ) -> Iterator[T]:
        if not self.enabled or tqdm is None:
            yield from iterable
            return
        disable = not sys.stderr.isatty()
        with tqdm(iterable, desc=desc, total=total, disable=disable) as bar:
            if postfix:
                bar.set_postfix(postfix)
            for item in bar:
                yield item

    @contextmanager
    def progress(
        self,
        *,
        total: int,
        desc: str,
        postfix: dict[str, Any] | None = None,
    ):
        if not self.enabled or tqdm is None or not sys.stderr.isatty():
            yield _NoopProgress()
            return
        with tqdm(total=total, desc=desc) as bar:
            if postfix:
                bar.set_postfix(postfix)
            yield bar


class _NoopProgress:
    def update(self, n: int = 1) -> None:
        return None

    def set_postfix(self, *args: Any, **kwargs: Any) -> None:
        return None


class NullProgressReporter(ProgressReporter):
    def __init__(self) -> None:
        super().__init__(enabled=False)
