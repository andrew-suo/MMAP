"""Optimizer loop orchestration with optional checkpoint resume."""

from __future__ import annotations

import json
from pathlib import Path

from .checkpoint import CheckpointState, CheckpointStore
from .round_runner import RoundRunner


class OptimizerLoop:
    """Coordinate optimizer state initialization, resume, and round execution."""

    def __init__(
        self,
        *,
        checkpoint_path: str | Path = "checkpoint.json",
        fewshot_pool_path: str | Path = "fewshot_pool.json",
        sample_ids: list[str] | None = None,
        resume: bool = False,
    ) -> None:
        self.checkpoint_store = CheckpointStore(checkpoint_path)
        if resume:
            if not self.checkpoint_store.exists():
                raise FileNotFoundError(f"cannot resume; checkpoint not found: {checkpoint_path}")
            self.state = self.checkpoint_store.load()
        else:
            self.state = CheckpointState.initial(
                fewshot_pool_path=str(fewshot_pool_path),
                sample_ids=sample_ids,
            )
            self._ensure_fewshot_pool_exists(Path(fewshot_pool_path))

        self.round_runner = RoundRunner(self.state, self.checkpoint_store)

    def run(self, rounds: int) -> CheckpointState:
        """Run the requested number of additional rounds."""

        if rounds < 0:
            raise ValueError("rounds must be non-negative")
        for _ in range(rounds):
            self.state = self.round_runner.run_next_round()
        return self.state

    @staticmethod
    def _ensure_fewshot_pool_exists(path: Path) -> None:
        """Create an empty fewshot pool file if this is a fresh run."""

        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("w", encoding="utf-8") as pool_file:
                json.dump([], pool_file)
                pool_file.write("\n")
