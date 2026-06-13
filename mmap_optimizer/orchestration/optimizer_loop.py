"""Optimizer loop orchestration with checkpoint/resume support."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .checkpoint import Checkpoint, PromptSnapshot, checkpoint_path, load_checkpoint, write_checkpoint


@dataclass(frozen=True)
class OptimizerResult:
    """Result returned by an optimizer run."""

    completed_round_ids: list[str]
    latest_metrics_summary: dict[str, Any]
    checkpoint_path: Path


@dataclass
class OptimizerLoop:
    """Run prompt optimization rounds and persist resumable state.

    Parameters
    ----------
    run_dir:
        Directory where ``checkpoint.json`` and related run artifacts are stored.
    rounds:
        Number of rounds to execute in this invocation.
    resume:
        When true, restore active prompt state and the next round index from the
        existing checkpoint before executing additional rounds.
    """

    run_dir: str | Path
    rounds: int = 1
    resume: bool = False
    extraction_prompt_id: str = "extraction"
    analysis_prompt_id: str = "analysis"
    fewshot_pool_path: str | Path = "fewshot_pool.json"
    sample_states: dict[str, Any] = field(default_factory=dict)

    def run(self) -> OptimizerResult:
        if self.rounds < 0:
            raise ValueError("rounds must be non-negative")

        checkpoint = self._initial_checkpoint()
        for _ in range(self.rounds):
            round_id = self._format_round_id(checkpoint.next_round_index)
            if round_id in checkpoint.completed_round_ids:
                raise ValueError(f"checkpoint already contains round id {round_id}")

            latest_metrics_summary = self._run_round(round_id, checkpoint)
            completed_round_ids = [*checkpoint.completed_round_ids, round_id]

            checkpoint = Checkpoint(
                active_extraction_prompt=self._advance_prompt(
                    checkpoint.active_extraction_prompt,
                    round_id,
                    "extraction",
                ),
                active_analysis_prompt=self._advance_prompt(
                    checkpoint.active_analysis_prompt,
                    round_id,
                    "analysis",
                ),
                completed_round_ids=completed_round_ids,
                sample_states=self._update_sample_states(round_id, checkpoint.sample_states),
                fewshot_pool_path=str(self.fewshot_pool_path),
                latest_metrics_summary=latest_metrics_summary,
                next_round_index=checkpoint.next_round_index + 1,
            )
            write_checkpoint(self.run_dir, checkpoint)

        return OptimizerResult(
            completed_round_ids=checkpoint.completed_round_ids,
            latest_metrics_summary=checkpoint.latest_metrics_summary,
            checkpoint_path=checkpoint_path(self.run_dir),
        )

    def _initial_checkpoint(self) -> Checkpoint:
        if self.resume:
            path = checkpoint_path(self.run_dir)
            if not path.exists():
                raise FileNotFoundError(f"cannot resume without checkpoint: {path}")
            return load_checkpoint(self.run_dir)

        return Checkpoint(
            active_extraction_prompt=self._prompt_snapshot(
                self.extraction_prompt_id,
                1,
                "initial extraction prompt v1",
            ),
            active_analysis_prompt=self._prompt_snapshot(
                self.analysis_prompt_id,
                1,
                "initial analysis prompt v1",
            ),
            completed_round_ids=[],
            sample_states=dict(self.sample_states),
            fewshot_pool_path=str(self.fewshot_pool_path),
            latest_metrics_summary={},
            next_round_index=1,
        )

    def _run_round(self, round_id: str, checkpoint: Checkpoint) -> dict[str, Any]:
        return {
            "round_id": round_id,
            "completed_round_count": len(checkpoint.completed_round_ids) + 1,
            "extraction_prompt_version": checkpoint.active_extraction_prompt.version,
            "analysis_prompt_version": checkpoint.active_analysis_prompt.version,
        }

    def _advance_prompt(
        self,
        prompt: PromptSnapshot,
        round_id: str,
        prompt_kind: str,
    ) -> PromptSnapshot:
        next_version = prompt.version + 1
        rendered = f"{prompt.prompt_id}:{prompt_kind}:v{next_version}:after:{round_id}"
        return self._prompt_snapshot(prompt.prompt_id, next_version, rendered)

    def _prompt_snapshot(self, prompt_id: str, version: int, rendered: str) -> PromptSnapshot:
        return PromptSnapshot.from_rendered(prompt_id=prompt_id, version=version, rendered=rendered)

    def _update_sample_states(
        self,
        round_id: str,
        previous_sample_states: dict[str, Any],
    ) -> dict[str, Any]:
        sample_states = dict(previous_sample_states)
        sample_states[round_id] = {"status": "completed"}
        return sample_states

    def _format_round_id(self, round_index: int) -> str:
        return f"round-{round_index:04d}"
