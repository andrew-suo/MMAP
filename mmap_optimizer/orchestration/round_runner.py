"""Round runner utilities that persist LLM step artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, TypeVar

from mmap_optimizer.orchestration.llm_records import capture_llm_steps, write_llm_steps_jsonl

T = TypeVar("T")


class RoundWork(Protocol[T]):
    def __call__(self) -> T: ...


@dataclass(slots=True)
class RoundResult:
    round_id: str
    artifact_dir: Path
    llm_steps_path: Path
    result: object
    llm_step_count: int


class RoundRunner:
    """Run one optimizer round and write ``round_xxxxxx/llm_steps.jsonl``."""

    def __init__(self, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root)

    def run_round(self, round_id: str | int, work: RoundWork[T]) -> RoundResult:
        normalized_round_id = normalize_round_id(round_id)
        round_dir = self.artifact_root / normalized_round_id
        llm_steps_path = round_dir / "llm_steps.jsonl"
        with capture_llm_steps(normalized_round_id) as records:
            result = work()
        write_llm_steps_jsonl(llm_steps_path, records)
        return RoundResult(
            round_id=normalized_round_id,
            artifact_dir=round_dir,
            llm_steps_path=llm_steps_path,
            result=result,
            llm_step_count=len(records),
        )


def normalize_round_id(round_id: str | int) -> str:
    """Normalize round ids to the artifact directory format."""

    if isinstance(round_id, int):
        return f"round_{round_id:06d}"
    if round_id.startswith("round_"):
        return round_id
    if round_id.isdigit():
        return f"round_{int(round_id):06d}"
    return round_id


def run_round(round_id: str | int, artifact_root: str | Path, work: Callable[[], T]) -> RoundResult:
    """Convenience wrapper around :class:`RoundRunner`."""

    return RoundRunner(artifact_root).run_round(round_id, work)
