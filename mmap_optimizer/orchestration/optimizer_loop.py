"""A resumable optimizer loop with prompt snapshot rollback support."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .checkpoint import OptimizerCheckpoint, PromptSnapshot, rendered_hash


@dataclass(slots=True)
class _ActivePrompt:
    name: str
    version: int
    rendered: str
    snapshot_id: str | None = None
    snapshot_path: str | None = None

    def checkpoint_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "rendered_hash": rendered_hash(self.rendered),
            "rendered": self.rendered,
            "snapshot_id": self.snapshot_id,
            "snapshot_path": self.snapshot_path,
        }


class OptimizerLoop:
    """Run optimizer rounds while persisting checkpoints and prompt snapshots.

    Parameters
    ----------
    output_dir:
        Run directory that receives ``checkpoint.json`` and ``round_xxxxxx``
        subdirectories.
    rounds:
        Number of additional rounds to execute for this invocation.
    resume:
        When true, initialize state from ``output_dir/checkpoint.json`` and
        continue at the next round index.
    rollback_to_snapshot_id:
        Optional prompt snapshot id to restore before executing new rounds.
    """

    def __init__(
        self,
        output_dir: str | Path,
        *,
        rounds: int = 1,
        extraction_prompt: str = "Extract structured fields from the sample.",
        analysis_prompt: str = "Analyze extraction quality and propose improvements.",
        fewshot_pool_path: str | Path | None = None,
        sample_states: list[dict[str, Any]] | None = None,
        metrics_summary: dict[str, Any] | None = None,
        resume: bool = False,
        rollback_to_snapshot_id: str | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.rounds = rounds
        self.fewshot_pool_path = None if fewshot_pool_path is None else str(fewshot_pool_path)
        self.sample_states = list(sample_states or [])
        self.metrics_summary = dict(metrics_summary or {})
        self.active_prompts: dict[str, _ActivePrompt] = {
            "extraction": _ActivePrompt("extraction", 1, extraction_prompt),
            "analysis": _ActivePrompt("analysis", 1, analysis_prompt),
        }
        self.next_round_index = 0

        if resume:
            self._resume_from_checkpoint()
        if rollback_to_snapshot_id is not None:
            self.rollback_to_snapshot(rollback_to_snapshot_id)

    @property
    def checkpoint_path(self) -> Path:
        """The run-level checkpoint path."""

        return self.output_dir / "checkpoint.json"

    def run(self) -> OptimizerCheckpoint:
        """Execute configured rounds and return the latest checkpoint."""

        latest_checkpoint: OptimizerCheckpoint | None = None
        for round_index in range(self.next_round_index, self.next_round_index + self.rounds):
            self._write_prompt_snapshots(round_index, stage="before")
            self._promote_prompts(round_index)
            self._write_prompt_snapshots(round_index, stage="after")
            latest_checkpoint = self.write_checkpoint(round_index)
        if latest_checkpoint is None:
            latest_checkpoint = self.write_checkpoint(self.next_round_index - 1)
        self.next_round_index += self.rounds
        return latest_checkpoint

    def write_checkpoint(self, round_index: int) -> OptimizerCheckpoint:
        """Write end-of-round optimizer state to ``checkpoint.json``."""

        checkpoint = OptimizerCheckpoint(
            round_index=round_index,
            active_prompts={name: prompt.checkpoint_payload() for name, prompt in self.active_prompts.items()},
            sample_states=self.sample_states,
            fewshot_pool_path=self.fewshot_pool_path,
            metrics_summary=self.metrics_summary,
        )
        checkpoint.save(self.checkpoint_path)
        return checkpoint

    def rollback_to_snapshot(self, snapshot_id: str) -> PromptSnapshot:
        """Restore the active prompt named by ``snapshot_id``.

        The matching snapshot is searched under ``round_*/prompts`` in the run
        directory. Only the prompt represented by the snapshot is changed; the
        other active prompt remains at its current version.
        """

        snapshot_path = self._find_snapshot_path(snapshot_id)
        snapshot = PromptSnapshot.load(snapshot_path)
        self.active_prompts[snapshot.prompt_name] = _ActivePrompt(
            snapshot.prompt_name,
            snapshot.version,
            snapshot.rendered,
            snapshot.snapshot_id,
            str(snapshot_path),
        )
        return snapshot

    def _resume_from_checkpoint(self) -> None:
        if not self.checkpoint_path.exists():
            raise FileNotFoundError(f"Cannot resume without checkpoint: {self.checkpoint_path}")
        checkpoint = OptimizerCheckpoint.load(self.checkpoint_path)
        self.next_round_index = checkpoint.round_index + 1
        self.sample_states = checkpoint.sample_states
        self.fewshot_pool_path = checkpoint.fewshot_pool_path
        self.metrics_summary = checkpoint.metrics_summary
        for name, payload in checkpoint.active_prompts.items():
            self.active_prompts[name] = _ActivePrompt(
                name=name,
                version=int(payload["version"]),
                rendered=str(payload.get("rendered", "")),
                snapshot_id=payload.get("snapshot_id"),
                snapshot_path=payload.get("snapshot_path"),
            )

    def _promote_prompts(self, round_index: int) -> None:
        for prompt in self.active_prompts.values():
            prompt.version += 1
            prompt.rendered = f"{prompt.rendered}\n\n[promoted in round {round_index:06d} to v{prompt.version:06d}]"

    def _write_prompt_snapshots(self, round_index: int, *, stage: str) -> None:
        prompt_dir = self.output_dir / f"round_{round_index:06d}" / "prompts"
        for prompt in self.active_prompts.values():
            snapshot_id = f"round_{round_index:06d}_{prompt.name}_{stage}_v{prompt.version:06d}"
            snapshot = PromptSnapshot.create(
                snapshot_id=snapshot_id,
                prompt_name=prompt.name,
                version=prompt.version,
                rendered=prompt.rendered,
                round_index=round_index,
                stage=stage,
            )
            snapshot_path = prompt_dir / f"{snapshot_id}.json"
            snapshot.save(snapshot_path)
            prompt.snapshot_id = snapshot_id
            prompt.snapshot_path = str(snapshot_path)

    def _find_snapshot_path(self, snapshot_id: str) -> Path:
        direct_matches = sorted(self.output_dir.glob(f"round_*/prompts/{snapshot_id}.json"))
        if direct_matches:
            return direct_matches[-1]

        for snapshot_path in sorted(self.output_dir.glob("round_*/prompts/*.json")):
            try:
                snapshot = PromptSnapshot.load(snapshot_path)
            except (KeyError, ValueError):
                continue
            if snapshot.snapshot_id == snapshot_id:
                return snapshot_path
        raise FileNotFoundError(f"Prompt snapshot not found: {snapshot_id}")
