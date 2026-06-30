from __future__ import annotations

import argparse
import json
from pathlib import Path

from mmap_optimizer.core.cli import eval_latest_command
from mmap_optimizer.core.config import RefactoredConfig
from mmap_optimizer.core.latest_prompt_eval import (
    EvaluationSummary,
    LatestPromptEvaluationResult,
    LatestPromptEvaluator,
    PerSampleEvaluationRecord,
    resolve_latest_extraction_prompt,
)
from mmap_optimizer.core.progress import ProgressReporter
from mmap_optimizer.executors.evaluation_executor import EvaluationExecutor
from mmap_optimizer.prompt.structured_prompt import PromptSection, StructuredPrompt
from mmap_optimizer.stages.extraction_prompt_optimization import ExtractionResult


class RecordingProgress(ProgressReporter):
    def __init__(self) -> None:
        super().__init__(enabled=False)
        self.lines: list[str] = []

    def iter(self, iterable, *, desc: str, total=None, postfix=None):
        yield from iterable

    def write(self, message: str) -> None:
        self.lines.append(message)


class FakeExtractionExecutor:
    def __init__(self, outputs: dict[str, ExtractionResult]) -> None:
        self.outputs = outputs
        self.progress_reporter = None

    def execute(self, prompt, batch, sample_set, fewshot_examples=None):
        return [self.outputs[batch.sample_ids[0]]]


def _prompt_dict() -> dict:
    prompt = StructuredPrompt(
        id="prompt_final",
        prompt_type="extraction",
        sections=[
            PromptSection(
                id="section_1",
                title="Task",
                level=1,
                content="Extract result",
            )
        ],
        raw_markdown="# Task\nExtract result",
    )
    return prompt.to_dict()


def _write_dataset(path: Path) -> None:
    rows = [
        {"id": "s1", "input": {"text": "a"}, "ground_truth": {"result": "OK"}},
        {"id": "s2", "input": {"text": "b"}, "ground_truth": {"result": "OK"}},
        {"id": "s3", "input": {"text": "c"}, "ground_truth": {"result": "OK"}},
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")


def test_resolve_latest_extraction_prompt_prefers_final_then_current(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    current = run_dir / "current_extraction_prompt.json"
    final = run_dir / "final_extraction_prompt.json"
    current.write_text("{}", encoding="utf-8")
    assert resolve_latest_extraction_prompt(run_dir) == current
    final.write_text("{}", encoding="utf-8")
    assert resolve_latest_extraction_prompt(run_dir) == final


def test_latest_prompt_evaluator_writes_artifacts_and_counts_invalid(
    tmp_path: Path,
    monkeypatch,
):
    dataset_path = tmp_path / "dataset.jsonl"
    _write_dataset(dataset_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "final_extraction_prompt.json").write_text(
        json.dumps(_prompt_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "final_fewshot_examples.jsonl").write_text(
        json.dumps(
            {
                "id": "fs1",
                "sample_id": "s1",
                "input_text": "fewshot input",
                "output_text": '{"result": "OK"}',
                "input_images": [],
                "output_data": {"result": "OK"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    outputs = {
        "s1": ExtractionResult(
            sample_id="s1",
            raw_output='{"result":"OK"}',
            parsed_output={"result": "OK"},
            status="correct",
        ),
        "s2": ExtractionResult(
            sample_id="s2",
            raw_output='{"result":"BAD"}',
            parsed_output={"result": "BAD"},
            status="correct",
        ),
        "s3": ExtractionResult(
            sample_id="s3",
            raw_output="not json",
            parsed_output=None,
            status="invalid",
        ),
    }

    def fake_create_executors(config_dict, use_mock=None):
        return {
            "extraction": FakeExtractionExecutor(outputs),
            "evaluation": EvaluationExecutor(primary_answer_fields=["result"]),
        }

    monkeypatch.setattr(
        "mmap_optimizer.core.latest_prompt_eval.create_executors",
        fake_create_executors,
    )

    config = RefactoredConfig()
    config.dataset.path = str(dataset_path)
    config.run.output_dir = str(run_dir)
    progress = RecordingProgress()
    evaluator = LatestPromptEvaluator(
        config,
        run_dir=run_dir,
        artifact_dir=tmp_path / "artifacts",
        progress_reporter=progress,
    )
    result = evaluator.run()

    assert result.summary.total_count == 3
    assert result.summary.correct_count == 1
    assert result.summary.wrong_count == 1
    assert result.summary.invalid_count == 1
    assert result.summary.exact_match_accuracy == 1 / 3

    assert len(progress.lines) == 3
    assert "evaluation=correct" in progress.lines[0]
    assert "evaluation=wrong" in progress.lines[1]
    assert "evaluation=invalid" in progress.lines[2]

    artifact_dir = Path(result.artifact_dir)
    assert (artifact_dir / "used_extraction_prompt.json").exists()
    assert (artifact_dir / "used_fewshot_examples.jsonl").exists()
    assert (artifact_dir / "per_sample_results.jsonl").exists()
    assert (artifact_dir / "evaluation_summary.json").exists()
    assert (artifact_dir / "run_context.json").exists()

    summary_data = json.loads((artifact_dir / "evaluation_summary.json").read_text(encoding="utf-8"))
    assert summary_data["summary"]["total_count"] == 3
    assert summary_data["summary"]["invalid_count"] == 1
    assert summary_data["summary"]["exact_match_accuracy"] == 1 / 3

    result_lines = (artifact_dir / "per_sample_results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(result_lines) == 3


def test_latest_prompt_evaluator_does_not_modify_existing_run_state_files(
    tmp_path: Path,
    monkeypatch,
):
    dataset_path = tmp_path / "dataset.jsonl"
    _write_dataset(dataset_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "current_extraction_prompt.json").write_text(
        json.dumps(_prompt_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    states_file = run_dir / "sample_states.json"
    original_states = {"s1": {"sample_id": "s1", "error_count": 99}}
    states_file.write_text(json.dumps(original_states, ensure_ascii=False), encoding="utf-8")

    outputs = {
        sid: ExtractionResult(
            sample_id=sid,
            raw_output='{"result":"OK"}',
            parsed_output={"result": "OK"},
            status="correct",
        )
        for sid in ("s1", "s2", "s3")
    }

    def fake_create_executors(config_dict, use_mock=None):
        return {
            "extraction": FakeExtractionExecutor(outputs),
            "evaluation": EvaluationExecutor(primary_answer_fields=["result"]),
        }

    monkeypatch.setattr(
        "mmap_optimizer.core.latest_prompt_eval.create_executors",
        fake_create_executors,
    )

    config = RefactoredConfig()
    config.dataset.path = str(dataset_path)
    config.run.output_dir = str(run_dir)
    evaluator = LatestPromptEvaluator(
        config,
        run_dir=run_dir,
        artifact_dir=tmp_path / "artifacts",
        progress_reporter=RecordingProgress(),
    )
    evaluator.run()

    reloaded_states = json.loads(states_file.read_text(encoding="utf-8"))
    assert reloaded_states == original_states


def test_eval_latest_command_prints_summary(tmp_path: Path, monkeypatch, capsys):
    config = RefactoredConfig()
    config.run.output_dir = str(tmp_path / "run")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "run:\n"
        f"  output_dir: {config.run.output_dir}\n"
        "dataset:\n"
        "  path: data/smoke_samples.jsonl\n",
        encoding="utf-8",
    )

    def fake_run(self):
        return LatestPromptEvaluationResult(
            prompt_path=str(Path("run") / "final_extraction_prompt.json"),
            fewshot_path=None,
            artifact_dir=str(tmp_path / "artifacts"),
            summary=EvaluationSummary(
                total_count=5,
                correct_count=3,
                wrong_count=1,
                invalid_count=1,
                exact_match_accuracy=0.6,
            ),
            per_sample_results=[
                PerSampleEvaluationRecord(
                    sample_id="s1",
                    extraction_status="correct",
                    evaluation_status="correct",
                    correct=True,
                    raw_output="{}",
                    parsed_output={},
                )
            ],
        )

    monkeypatch.setattr(LatestPromptEvaluator, "run", fake_run)

    args = argparse.Namespace(
        config=str(config_path),
        run_dir=None,
        artifact_dir=None,
        use_mock=False,
        no_mock=False,
    )
    eval_latest_command(args)

    out = capsys.readouterr().out
    assert "Latest Extraction Prompt Full Evaluation" in out
    assert "Total/Correct/Wrong/Invalid: 5/3/1/1" in out
    assert "Exact-match Accuracy: 0.6000" in out
