"""Evaluate the latest extraction prompt on the full dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.artifacts import write_json_artifact, write_jsonl_artifact
from ..core.config import RefactoredConfig
from ..core.progress import NullProgressReporter, ProgressReporter
from ..data.dataset_loader import DatasetLoader
from ..data.sample import SampleBatch
from ..executors import create_executors
from ..phases.fewshot_optimization import FewshotExample
from ..prompt.structured_prompt import StructuredPrompt


@dataclass
class PerSampleEvaluationRecord:
    sample_id: str
    extraction_status: str
    evaluation_status: str
    correct: bool
    raw_output: str
    parsed_output: dict[str, Any] | None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "extraction_status": self.extraction_status,
            "evaluation_status": self.evaluation_status,
            "correct": self.correct,
            "raw_output": self.raw_output,
            "parsed_output": self.parsed_output,
            "details": dict(self.details),
        }


@dataclass
class EvaluationSummary:
    total_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    invalid_count: int = 0
    exact_match_accuracy: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_count": self.total_count,
            "correct_count": self.correct_count,
            "wrong_count": self.wrong_count,
            "invalid_count": self.invalid_count,
            "exact_match_accuracy": self.exact_match_accuracy,
        }


@dataclass
class LatestPromptEvaluationResult:
    prompt_path: str
    fewshot_path: str | None
    artifact_dir: str
    summary: EvaluationSummary
    per_sample_results: list[PerSampleEvaluationRecord] = field(default_factory=list)


def resolve_latest_extraction_prompt(run_dir: Path) -> Path:
    candidates = [
        run_dir / "final_extraction_prompt.json",
        run_dir / "current_extraction_prompt.json",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        f"latest extraction prompt artifact not found in {run_dir} "
        "(expected final_extraction_prompt.json or current_extraction_prompt.json)"
    )


def load_fewshot_examples(run_dir: Path) -> tuple[list[FewshotExample], Path | None]:
    fewshot_file = run_dir / "final_fewshot_examples.jsonl"
    if not fewshot_file.exists():
        return [], None
    examples: list[FewshotExample] = []
    for line in fewshot_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            examples.append(FewshotExample.from_dict(json.loads(line)))
    return examples, fewshot_file


def default_artifact_dir(run_dir: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return run_dir / "evaluations" / f"eval_latest_{ts}"


class LatestPromptEvaluator:
    """Evaluate the latest extraction prompt on the full dataset."""

    def __init__(
        self,
        config: RefactoredConfig,
        *,
        run_dir: Path,
        artifact_dir: Path | None = None,
        use_mock: bool | None = None,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self.config = config
        self.run_dir = run_dir
        self.artifact_dir = artifact_dir or default_artifact_dir(run_dir)
        self.use_mock = use_mock
        self.progress = progress_reporter or NullProgressReporter()

    def run(self) -> LatestPromptEvaluationResult:
        started_at = datetime.now().isoformat()
        prompt_path = resolve_latest_extraction_prompt(self.run_dir)
        prompt = StructuredPrompt.from_dict(json.loads(prompt_path.read_text(encoding="utf-8")))
        fewshot_examples, fewshot_path = load_fewshot_examples(self.run_dir)

        loader = DatasetLoader(
            dataset_path=self.config.dataset.path,
            format=self.config.dataset.format,
            image_root=self.config.dataset.image_root,
        )
        sample_set = loader.load_with_ground_truth(self.config.dataset.ground_truth_path)
        sample_ids = list(sample_set.specs.keys())

        executors = create_executors(self.config.to_dict(), use_mock=self.use_mock)
        extraction_executor = executors["extraction"]
        evaluation_executor = executors["evaluation"]
        if hasattr(extraction_executor, "progress_reporter"):
            extraction_executor.progress_reporter = NullProgressReporter()

        per_sample_results: list[PerSampleEvaluationRecord] = []
        for sample_id in self.progress.iter(
            sample_ids,
            desc="Evaluating samples",
            total=len(sample_ids),
        ):
            batch = SampleBatch(
                id=f"eval_{sample_id}",
                phase="evaluation",
                iteration=1,
                sample_ids=[sample_id],
                sampler_name="full_eval",
            )
            extraction_results = extraction_executor.execute(
                prompt,
                batch,
                sample_set,
                fewshot_examples or None,
            )
            if not extraction_results:
                continue
            extraction_result = extraction_results[0]
            eval_records = evaluation_executor.evaluate_batch(extraction_results, sample_set)
            if not eval_records:
                continue
            eval_record = eval_records[0]
            record = PerSampleEvaluationRecord(
                sample_id=sample_id,
                extraction_status=extraction_result.status,
                evaluation_status=eval_record.status,
                correct=eval_record.correct,
                raw_output=extraction_result.raw_output,
                parsed_output=extraction_result.parsed_output,
                details=eval_record.details,
            )
            per_sample_results.append(record)
            self.progress.write(self._format_sample_line(record))

        summary = self._summarize(per_sample_results)
        self._write_artifacts(
            prompt=prompt,
            prompt_path=prompt_path,
            fewshot_examples=fewshot_examples,
            fewshot_path=fewshot_path,
            summary=summary,
            per_sample_results=per_sample_results,
            started_at=started_at,
            ended_at=datetime.now().isoformat(),
        )
        return LatestPromptEvaluationResult(
            prompt_path=str(prompt_path),
            fewshot_path=str(fewshot_path) if fewshot_path is not None else None,
            artifact_dir=str(self.artifact_dir),
            summary=summary,
            per_sample_results=per_sample_results,
        )

    @staticmethod
    def _summarize(records: list[PerSampleEvaluationRecord]) -> EvaluationSummary:
        total_count = len(records)
        correct_count = sum(1 for record in records if record.correct)
        wrong_count = sum(1 for record in records if record.evaluation_status == "wrong")
        invalid_count = sum(1 for record in records if record.evaluation_status == "invalid")
        accuracy = (correct_count / total_count) if total_count else 0.0
        return EvaluationSummary(
            total_count=total_count,
            correct_count=correct_count,
            wrong_count=wrong_count,
            invalid_count=invalid_count,
            exact_match_accuracy=accuracy,
        )

    @staticmethod
    def _format_sample_line(record: PerSampleEvaluationRecord) -> str:
        suffix = ""
        if record.evaluation_status == "wrong":
            mismatched = record.details.get("mismatched_fields", [])
            if mismatched:
                suffix = f" mismatched={mismatched}"
        elif record.evaluation_status == "invalid":
            reason = record.details.get("reason")
            if reason:
                suffix = f" reason={reason}"
        return (
            f"[sample] {record.sample_id} "
            f"extraction={record.extraction_status} "
            f"evaluation={record.evaluation_status} "
            f"correct={record.correct}{suffix}"
        )

    def _write_artifacts(
        self,
        *,
        prompt: StructuredPrompt,
        prompt_path: Path,
        fewshot_examples: list[FewshotExample],
        fewshot_path: Path | None,
        summary: EvaluationSummary,
        per_sample_results: list[PerSampleEvaluationRecord],
        started_at: str,
        ended_at: str,
    ) -> None:
        write_json_artifact(self.artifact_dir / "used_extraction_prompt.json", prompt)
        if fewshot_examples:
            write_jsonl_artifact(
                self.artifact_dir / "used_fewshot_examples.jsonl",
                fewshot_examples,
            )
        write_jsonl_artifact(
            self.artifact_dir / "per_sample_results.jsonl",
            per_sample_results,
        )
        write_json_artifact(
            self.artifact_dir / "evaluation_summary.json",
            {
                "prompt_path": str(prompt_path),
                "fewshot_path": str(fewshot_path) if fewshot_path is not None else None,
                "summary": summary,
            },
        )
        write_json_artifact(
            self.artifact_dir / "run_context.json",
            {
                "config_dataset_path": self.config.dataset.path,
                "run_dir": str(self.run_dir),
                "artifact_dir": str(self.artifact_dir),
                "prompt_path": str(prompt_path),
                "fewshot_path": str(fewshot_path) if fewshot_path is not None else None,
                "started_at": started_at,
                "ended_at": ended_at,
            },
        )


__all__ = [
    "EvaluationSummary",
    "LatestPromptEvaluationResult",
    "LatestPromptEvaluator",
    "PerSampleEvaluationRecord",
    "default_artifact_dir",
    "load_fewshot_examples",
    "resolve_latest_extraction_prompt",
]
