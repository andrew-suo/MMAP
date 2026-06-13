"""Round orchestration utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

from mmap_optimizer.orchestration.llm_records import LLMStepRecorder, use_llm_step_recorder

T = TypeVar("T")


@dataclass(slots=True)
class RoundRunner:
    """Run one optimization round with a round-scoped LLM step recorder."""

    artifact_root: str | Path
    round_id: str | int
    record_llm_steps: bool | None = None

    @property
    def normalized_round_id(self) -> str:
        if isinstance(self.round_id, int):
            return f"round_{self.round_id:06d}"
        text = str(self.round_id)
        return text if text.startswith("round_") else f"round_{text}"

    @property
    def round_dir(self) -> Path:
        return Path(self.artifact_root) / self.normalized_round_id

    def make_recorder(self) -> LLMStepRecorder:
        return LLMStepRecorder(
            self.round_dir,
            self.normalized_round_id,
            enabled=self.record_llm_steps,
        )

    def run(self, fn: Callable[[], T]) -> T:
        """Run ``fn`` while step helpers write to ``round_xxxxxx/llm_steps.jsonl``."""

        recorder = self.make_recorder()
        self.round_dir.mkdir(parents=True, exist_ok=True)
        with use_llm_step_recorder(recorder):
            return fn()


def run_round(
    artifact_root: str | Path,
    round_id: str | int,
    fn: Callable[[], T],
    *,
    record_llm_steps: bool | None = None,
) -> T:
    return RoundRunner(artifact_root, round_id, record_llm_steps=record_llm_steps).run(fn)
