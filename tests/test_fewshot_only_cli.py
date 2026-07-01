from __future__ import annotations

import argparse
import json
from pathlib import Path

from mmap_optimizer.core.cli import optimize_fewshot_command
from mmap_optimizer.core.config import RefactoredConfig
from mmap_optimizer.core.fewshot_only import FewshotOnlyOptimizationResult, FewshotOnlyOptimizer, FewshotOnlySummary
from mmap_optimizer.phases.fewshot_optimization import FewshotExample
from mmap_optimizer.prompt.structured_prompt import PromptSection, StructuredPrompt


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


def _write_fewshot_file(path: Path) -> None:
    example = FewshotExample(
        id="fs1",
        sample_id="s1",
        input_text="fewshot input",
        output_text='{"result":"OK"}',
        input_images=[],
        output_data={"result": "OK"},
    )
    path.write_text(json.dumps(example.to_dict(), ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text_prompt(path: Path) -> str:
    text = "You are an extraction assistant.\nReturn the final result as JSON with a result field."
    path.write_text(text, encoding="utf-8")
    return text


def _write_markdown_prompt(path: Path) -> str:
    text = "# Task\nExtract the result.\n\n## Output Format\n{\"result\": \"string\"}"
    path.write_text(text, encoding="utf-8")
    return text


def _write_gbk_text_prompt(path: Path) -> str:
    text = "你是一个抽取助手。\n请输出包含 result 字段的 JSON。"
    path.write_bytes(text.encode("gbk"))
    return text


def _config(dataset_path: Path, output_dir: Path) -> RefactoredConfig:
    config = RefactoredConfig()
    config.dataset.path = str(dataset_path)
    config.run.output_dir = str(output_dir)
    config.run.use_mock = True
    config.fewshot_optimization.rounds = 1
    config.fewshot_optimization.batch_size = 2
    config.fewshot_optimization.slot_count = 1
    return config


def test_fewshot_only_optimizer_with_prompt_file_writes_artifacts(tmp_path: Path):
    dataset_path = tmp_path / "dataset.jsonl"
    _write_dataset(dataset_path)
    prompt_file = tmp_path / "prompt.json"
    prompt_file.write_text(json.dumps(_prompt_dict(), ensure_ascii=False), encoding="utf-8")

    artifact_dir = tmp_path / "fewshot_only_out"
    optimizer = FewshotOnlyOptimizer(
        _config(dataset_path, tmp_path / "base_out"),
        prompt_file=prompt_file,
        artifact_dir=artifact_dir,
        use_mock=True,
    )

    result = optimizer.run()

    assert result.summary.iterations == 1
    assert result.summary.initial_fewshot_count == 0
    assert (artifact_dir / "used_extraction_prompt.json").exists()
    assert (artifact_dir / "initial_fewshot_examples.jsonl").exists()
    assert (artifact_dir / "final_fewshot_examples.jsonl").exists()
    assert (artifact_dir / "fewshot_only_summary.json").exists()
    assert (artifact_dir / "sample_states.json").exists()
    assert (artifact_dir / "sample_traces.jsonl").exists()
    assert (artifact_dir / "fewshot_optimization" / "iteration_1" / "fewshot" / "metrics.json").exists()
    run_context = json.loads((artifact_dir / "run_context.json").read_text(encoding="utf-8"))
    assert run_context["prompt_input_format"] == "structured_json"
    assert run_context["prompt_text_encoding"] == "utf-8"
    assert run_context["prompt_conversion_applied"] is False
    assert not (artifact_dir / "source_prompt.txt").exists()


def test_fewshot_only_optimizer_accepts_plain_text_prompt_file(tmp_path: Path):
    dataset_path = tmp_path / "dataset.jsonl"
    _write_dataset(dataset_path)
    prompt_file = tmp_path / "prompt.txt"
    prompt_text = _write_text_prompt(prompt_file)

    artifact_dir = tmp_path / "fewshot_only_out"
    optimizer = FewshotOnlyOptimizer(
        _config(dataset_path, tmp_path / "base_out"),
        prompt_file=prompt_file,
        artifact_dir=artifact_dir,
        use_mock=True,
    )

    result = optimizer.run()

    assert result.summary.iterations == 1
    used_prompt = json.loads((artifact_dir / "used_extraction_prompt.json").read_text(encoding="utf-8"))
    run_context = json.loads((artifact_dir / "run_context.json").read_text(encoding="utf-8"))
    assert used_prompt["prompt_type"] == "extraction"
    assert len(used_prompt["sections"]) == 1
    assert used_prompt["sections"][0]["title"] == "Instructions"
    assert used_prompt["sections"][0]["content"] == prompt_text
    assert run_context["prompt_input_format"] == "raw_text"
    assert run_context["prompt_text_encoding"] == "utf-8"
    assert run_context["prompt_conversion_applied"] is True
    assert (artifact_dir / "source_prompt.txt").read_text(encoding="utf-8") == prompt_text


def test_fewshot_only_optimizer_accepts_markdown_prompt_file(tmp_path: Path):
    dataset_path = tmp_path / "dataset.jsonl"
    _write_dataset(dataset_path)
    prompt_file = tmp_path / "prompt.md"
    _write_markdown_prompt(prompt_file)

    artifact_dir = tmp_path / "fewshot_only_out"
    optimizer = FewshotOnlyOptimizer(
        _config(dataset_path, tmp_path / "base_out"),
        prompt_file=prompt_file,
        artifact_dir=artifact_dir,
        use_mock=True,
    )

    optimizer.run()

    used_prompt = json.loads((artifact_dir / "used_extraction_prompt.json").read_text(encoding="utf-8"))
    run_context = json.loads((artifact_dir / "run_context.json").read_text(encoding="utf-8"))
    assert len(used_prompt["sections"]) >= 1
    assert used_prompt["sections"][0]["title"] == "Task"
    assert run_context["prompt_input_format"] == "raw_text"
    assert run_context["prompt_text_encoding"] == "utf-8"
    assert run_context["prompt_conversion_applied"] is True


def test_fewshot_only_optimizer_accepts_gbk_plain_text_prompt_file(tmp_path: Path):
    dataset_path = tmp_path / "dataset.jsonl"
    _write_dataset(dataset_path)
    prompt_file = tmp_path / "prompt_gbk.txt"
    prompt_text = _write_gbk_text_prompt(prompt_file)

    artifact_dir = tmp_path / "fewshot_only_out"
    optimizer = FewshotOnlyOptimizer(
        _config(dataset_path, tmp_path / "base_out"),
        prompt_file=prompt_file,
        artifact_dir=artifact_dir,
        use_mock=True,
    )

    result = optimizer.run()

    assert result.summary.iterations == 1
    used_prompt = json.loads((artifact_dir / "used_extraction_prompt.json").read_text(encoding="utf-8"))
    run_context = json.loads((artifact_dir / "run_context.json").read_text(encoding="utf-8"))
    assert used_prompt["sections"][0]["content"] == prompt_text
    assert run_context["prompt_input_format"] == "raw_text"
    assert run_context["prompt_text_encoding"] in {"gb18030", "gbk"}
    assert run_context["prompt_conversion_applied"] is True
    assert (artifact_dir / "source_prompt.txt").read_text(encoding="utf-8") == prompt_text


def test_fewshot_only_optimizer_uses_run_dir_initial_fewshot_without_mutating_source(tmp_path: Path):
    dataset_path = tmp_path / "dataset.jsonl"
    _write_dataset(dataset_path)
    run_dir = tmp_path / "source_run"
    run_dir.mkdir()
    (run_dir / "final_extraction_prompt.json").write_text(
        json.dumps(_prompt_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    _write_fewshot_file(run_dir / "final_fewshot_examples.jsonl")
    original_states = {"s1": {"sample_id": "s1", "error_count": 99}}
    (run_dir / "sample_states.json").write_text(
        json.dumps(original_states, ensure_ascii=False),
        encoding="utf-8",
    )
    original_summary = {"status": "completed"}
    (run_dir / "run_summary.json").write_text(
        json.dumps(original_summary, ensure_ascii=False),
        encoding="utf-8",
    )
    original_fewshot_text = (run_dir / "final_fewshot_examples.jsonl").read_text(encoding="utf-8")

    artifact_dir = tmp_path / "fewshot_only_out"
    optimizer = FewshotOnlyOptimizer(
        _config(dataset_path, tmp_path / "base_out"),
        run_dir=run_dir,
        artifact_dir=artifact_dir,
        use_mock=True,
    )

    result = optimizer.run()

    assert result.initial_fewshot_path == str(run_dir / "final_fewshot_examples.jsonl")
    initial_lines = (artifact_dir / "initial_fewshot_examples.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(initial_lines) == 1
    assert json.loads(initial_lines[0])["id"] == "fs1"
    assert json.loads((run_dir / "sample_states.json").read_text(encoding="utf-8")) == original_states
    assert json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8")) == original_summary
    assert (run_dir / "final_fewshot_examples.jsonl").read_text(encoding="utf-8") == original_fewshot_text


def test_fewshot_only_optimizer_requires_exactly_one_prompt_source(tmp_path: Path):
    dataset_path = tmp_path / "dataset.jsonl"
    _write_dataset(dataset_path)
    prompt_file = tmp_path / "prompt.json"
    prompt_file.write_text(json.dumps(_prompt_dict(), ensure_ascii=False), encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    try:
        FewshotOnlyOptimizer(
            _config(dataset_path, tmp_path / "out"),
            run_dir=run_dir,
            prompt_file=prompt_file,
            use_mock=True,
        )
    except ValueError as exc:
        assert "exactly one of run_dir or prompt_file" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_optimize_fewshot_command_prints_summary(tmp_path: Path, monkeypatch, capsys):
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
    prompt_file = tmp_path / "prompt.json"
    prompt_file.write_text(json.dumps(_prompt_dict(), ensure_ascii=False), encoding="utf-8")

    def fake_run(self):
        return FewshotOnlyOptimizationResult(
            prompt_path=str(prompt_file),
            initial_fewshot_path=None,
            artifact_dir=str(tmp_path / "artifacts"),
            summary=FewshotOnlySummary(
                prompt_source_path=str(prompt_file),
                initial_fewshot_source_path=None,
                iterations=2,
                base_accuracy_first=0.5,
                final_accuracy_last=0.75,
                accepted=True,
                initial_fewshot_count=0,
                final_fewshot_count=2,
            ),
            final_fewshot_examples=[],
        )

    monkeypatch.setattr("mmap_optimizer.core.fewshot_only.FewshotOnlyOptimizer.run", fake_run)

    args = argparse.Namespace(
        config=str(config_path),
        run_dir=None,
        prompt_file=str(prompt_file),
        initial_fewshot_file=None,
        output_dir=None,
        use_mock=None,
        no_mock=None,
    )
    optimize_fewshot_command(args)
    output = capsys.readouterr().out

    assert "Standalone Few-shot Optimization" in output
    assert f"Prompt: {prompt_file}" in output
    assert "Iterations: 2" in output
    assert "Base Accuracy: 0.5000" in output
    assert "Final Accuracy: 0.7500" in output
    assert "Initial/Final Few-shot Count: 0/2" in output
