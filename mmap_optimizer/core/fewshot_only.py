"""Run few-shot optimization against an existing extraction prompt."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.artifacts import write_json_artifact, write_jsonl_artifact
from ..core.config import RefactoredConfig
from ..core.latest_prompt_eval import load_fewshot_examples, resolve_latest_extraction_prompt
from ..core.progress import NullProgressReporter, ProgressReporter
from ..data.dataset_loader import DatasetLoader
from ..executors import create_executors
from ..phases.fewshot_optimization import FewshotExample, FewshotOptimizationPhase
from ..phases.prompt_structuring import PromptStructuringPhase
from ..prompt.structured_prompt import StructuredPrompt


@dataclass
class FewshotOnlySummary:
    prompt_source_path: str
    initial_fewshot_source_path: str | None
    iterations: int = 0
    base_accuracy_first: float | None = None
    final_accuracy_last: float | None = None
    accepted: bool = False
    initial_fewshot_count: int = 0
    final_fewshot_count: int = 0

    def to_dict(self) -> dict:
        return {
            "prompt_source_path": self.prompt_source_path,
            "initial_fewshot_source_path": self.initial_fewshot_source_path,
            "iterations": self.iterations,
            "base_accuracy_first": self.base_accuracy_first,
            "final_accuracy_last": self.final_accuracy_last,
            "accepted": self.accepted,
            "initial_fewshot_count": self.initial_fewshot_count,
            "final_fewshot_count": self.final_fewshot_count,
        }


@dataclass
class FewshotOnlyOptimizationResult:
    prompt_path: str
    initial_fewshot_path: str | None
    artifact_dir: str
    summary: FewshotOnlySummary
    final_fewshot_examples: list[FewshotExample] = field(default_factory=list)


@dataclass
class PromptLoadInfo:
    prompt: StructuredPrompt
    input_format: str
    conversion_applied: bool
    standardized: bool
    source_text: str | None = None


def load_fewshot_examples_from_file(path: Path) -> list[FewshotExample]:
    examples: list[FewshotExample] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            examples.append(FewshotExample.from_dict(json.loads(line)))
    return examples


def default_artifact_dir(base_output_dir: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base_output_dir / "fewshot_only" / ts


class FewshotOnlyOptimizer:
    """Run standalone few-shot optimization from an existing extraction prompt."""

    def __init__(
        self,
        config: RefactoredConfig,
        *,
        run_dir: Path | None = None,
        prompt_file: Path | None = None,
        initial_fewshot_file: Path | None = None,
        artifact_dir: Path | None = None,
        use_mock: bool | None = None,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        if (run_dir is None) == (prompt_file is None):
            raise ValueError("exactly one of run_dir or prompt_file must be provided")
        self.config = config
        self.run_dir = run_dir
        self.prompt_file = prompt_file
        self.initial_fewshot_file = initial_fewshot_file
        self.use_mock = use_mock
        self.progress = progress_reporter or NullProgressReporter()
        self.artifact_dir = artifact_dir or default_artifact_dir(Path(config.run.output_dir))

    def run(self) -> FewshotOnlyOptimizationResult:
        started_at = datetime.now().isoformat()
        prompt_path = self._resolve_prompt_path()
        runtime_config = RefactoredConfig.from_dict(self.config.to_dict())
        runtime_config.run.output_dir = str(self.artifact_dir)
        executors = create_executors(runtime_config.to_dict(), use_mock=self.use_mock)
        prompt_info = self._load_prompt(
            prompt_path,
            runtime_config=runtime_config,
            executors=executors,
        )
        prompt = prompt_info.prompt
        initial_examples, initial_fewshot_path = self._load_initial_fewshot_examples()

        loader = DatasetLoader(
            dataset_path=self.config.dataset.path,
            format=self.config.dataset.format,
            image_root=self.config.dataset.image_root,
        )
        sample_set = loader.load_with_ground_truth(self.config.dataset.ground_truth_path)

        phase = FewshotOptimizationPhase(
            config=runtime_config.fewshot_optimization,
            extraction_prompt=prompt,
            sample_set=sample_set,
            output_dir=self.artifact_dir,
            seed=runtime_config.run.seed,
            initial_fewshot_examples=initial_examples,
            fewshot_executor=executors.get("fewshot"),
            progress_reporter=self.progress,
        )
        results = phase.run()

        summary = self._summarize(
            prompt_path=prompt_path,
            initial_fewshot_path=initial_fewshot_path,
            initial_fewshot_count=len(initial_examples),
            final_fewshot_count=len(phase.fewshot_examples),
            results=results,
        )
        self._write_artifacts(
            prompt=prompt,
            prompt_path=prompt_path,
            prompt_info=prompt_info,
            initial_examples=initial_examples,
            initial_fewshot_path=initial_fewshot_path,
            final_examples=phase.fewshot_examples,
            sample_set=sample_set,
            summary=summary,
            started_at=started_at,
            ended_at=datetime.now().isoformat(),
        )
        return FewshotOnlyOptimizationResult(
            prompt_path=str(prompt_path),
            initial_fewshot_path=str(initial_fewshot_path) if initial_fewshot_path is not None else None,
            artifact_dir=str(self.artifact_dir),
            summary=summary,
            final_fewshot_examples=phase.fewshot_examples,
        )

    def _resolve_prompt_path(self) -> Path:
        if self.run_dir is not None:
            return resolve_latest_extraction_prompt(self.run_dir)
        assert self.prompt_file is not None
        return self.prompt_file

    def _load_prompt(
        self,
        prompt_path: Path,
        *,
        runtime_config: RefactoredConfig,
        executors: dict[str, Any],
    ) -> PromptLoadInfo:
        text = prompt_path.read_text(encoding="utf-8")
        prompt_data = self._try_load_structured_prompt_json(text)
        if prompt_data is not None:
            prompt = StructuredPrompt.from_dict(prompt_data)
            return PromptLoadInfo(
                prompt=prompt,
                input_format="structured_json",
                conversion_applied=False,
                standardized=bool(prompt.metadata.get("standardized", False)),
                source_text=None,
            )

        structuring_phase = PromptStructuringPhase(
            runtime_config.prompt_structuring,
            model_client=executors.get("optimizer_model_client") or executors.get("model_client"),
            model_config=executors.get("optimizer_model_config") or executors.get("extraction_model_config"),
        )
        prompt = structuring_phase.structure_prompt_text(
            text,
            prompt_type="extraction",
            prompt_id="fewshot_only_extraction_prompt",
        )
        if not prompt.sections:
            raise ValueError(f"unable to structure prompt from text: {prompt_path}")
        return PromptLoadInfo(
            prompt=prompt,
            input_format="raw_text",
            conversion_applied=True,
            standardized=bool(prompt.metadata.get("standardized", False)),
            source_text=text,
        )

    @staticmethod
    def _try_load_structured_prompt_json(text: str) -> dict[str, Any] | None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        required_keys = {"id", "prompt_type", "sections", "raw_markdown"}
        if not required_keys.issubset(data.keys()):
            return None
        if data.get("prompt_type") not in {"extraction", "analysis"}:
            return None
        if not isinstance(data.get("sections"), list):
            return None
        return data

    def _load_initial_fewshot_examples(self) -> tuple[list[FewshotExample], Path | None]:
        if self.initial_fewshot_file is not None:
            return load_fewshot_examples_from_file(self.initial_fewshot_file), self.initial_fewshot_file
        if self.run_dir is not None:
            return load_fewshot_examples(self.run_dir)
        return [], None

    def _summarize(
        self,
        *,
        prompt_path: Path,
        initial_fewshot_path: Path | None,
        initial_fewshot_count: int,
        final_fewshot_count: int,
        results: list,
    ) -> FewshotOnlySummary:
        summary = FewshotOnlySummary(
            prompt_source_path=str(prompt_path),
            initial_fewshot_source_path=(
                str(initial_fewshot_path) if initial_fewshot_path is not None else None
            ),
            initial_fewshot_count=initial_fewshot_count,
            final_fewshot_count=final_fewshot_count,
        )
        if results:
            summary.iterations = len(results)
            summary.base_accuracy_first = results[0].metrics.base_accuracy
            summary.final_accuracy_last = results[-1].metrics.final_accuracy
            summary.accepted = any(result.metrics.accepted for result in results)
        return summary

    def _write_artifacts(
        self,
        *,
        prompt: StructuredPrompt,
        prompt_path: Path,
        prompt_info: PromptLoadInfo,
        initial_examples: list[FewshotExample],
        initial_fewshot_path: Path | None,
        final_examples: list[FewshotExample],
        sample_set,
        summary: FewshotOnlySummary,
        started_at: str,
        ended_at: str,
    ) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        write_json_artifact(self.artifact_dir / "used_extraction_prompt.json", prompt)
        if prompt_info.source_text is not None:
            (self.artifact_dir / "source_prompt.txt").write_text(
                prompt_info.source_text,
                encoding="utf-8",
            )
        write_jsonl_artifact(self.artifact_dir / "initial_fewshot_examples.jsonl", initial_examples)
        write_jsonl_artifact(self.artifact_dir / "final_fewshot_examples.jsonl", final_examples)
        write_json_artifact(
            self.artifact_dir / "sample_states.json",
            {sample_id: state for sample_id, state in sample_set.states.items()},
        )
        write_jsonl_artifact(self.artifact_dir / "sample_traces.jsonl", sample_set.traces)
        write_json_artifact(self.artifact_dir / "fewshot_only_summary.json", summary)
        write_json_artifact(self.artifact_dir / "run_config.json", self.config.to_dict())
        write_json_artifact(
            self.artifact_dir / "run_context.json",
            {
                "dataset_path": self.config.dataset.path,
                "artifact_dir": str(self.artifact_dir),
                "source_run_dir": str(self.run_dir) if self.run_dir is not None else None,
                "prompt_path": str(prompt_path),
                "prompt_input_format": prompt_info.input_format,
                "prompt_conversion_applied": prompt_info.conversion_applied,
                "prompt_standardized": prompt_info.standardized,
                "initial_fewshot_path": (
                    str(initial_fewshot_path) if initial_fewshot_path is not None else None
                ),
                "started_at": started_at,
                "ended_at": ended_at,
            },
        )


__all__ = [
    "FewshotOnlyOptimizationResult",
    "FewshotOnlyOptimizer",
    "FewshotOnlySummary",
    "default_artifact_dir",
    "load_fewshot_examples_from_file",
]
