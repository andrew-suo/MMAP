from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmap_optimizer.core.config import OptimizerConfig
from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.dataset.loader import initial_sample_states, load_ground_truths, load_samples
from mmap_optimizer.evaluation.evaluator import Evaluator
from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.orchestration.checkpoint import OptimizerCheckpoint
from mmap_optimizer.orchestration.optimizer_loop import OptimizerLoop
from mmap_optimizer.orchestration.round_runner import OptimizerState, RoundRunner
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.initializer import initialize_prompt_from_file
from mmap_optimizer.storage.json_store import JsonStore


def _load_contract(path: Path, prompt_type: PromptType, contract_id: str) -> OutputSchemaContract:
    schema = json.loads(path.read_text(encoding="utf-8"))
    primary = schema.get("x-primary-answer-fields", ["result"])
    return OutputSchemaContract(id=contract_id, prompt_type=prompt_type, version=1, schema=schema, primary_answer_fields=primary)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _build_state():
    root = _project_root()
    data_dir = root / "data"
    extraction_contract = _load_contract(root / "schemas" / "extraction_output_schema.json", PromptType.EXTRACTION, "extraction_output_schema_v1")
    analysis_contract = _load_contract(root / "schemas" / "analysis_output_schema.json", PromptType.ANALYSIS, "analysis_output_schema_v1")
    extraction_prompt = initialize_prompt_from_file(str(root / "prompts" / "raw" / "extraction.txt"), PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_from_file(str(root / "prompts" / "raw" / "analysis.txt"), PromptType.ANALYSIS, analysis_contract)
    samples = load_samples(data_dir / "samples.jsonl")
    ground_truths = load_ground_truths(data_dir / "ground_truth.jsonl")
    return OptimizerState(
        samples=samples, assets={}, ground_truths=ground_truths,
        sample_states=initial_sample_states(samples),
        active_extraction_prompt=extraction_prompt, active_analysis_prompt=analysis_prompt,
        extraction_output_schema_contract=extraction_contract, analysis_output_schema_contract=analysis_contract,
    )


def _loop(store: JsonStore, *, resume: bool = False) -> OptimizerLoop:
    config = OptimizerConfig(batch_size=24, dynamic_validation_batch_size=48)
    runner = RoundRunner(model_client=MockModelClient(), evaluator=Evaluator(), store=store, config=config)
    return OptimizerLoop(runner=runner, store=store, config=config, resume=resume)


def test_checkpoint_is_written_during_loop(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    _loop(store).run(_build_state(), max_rounds=1)
    assert (tmp_path / "checkpoint.json").exists(), "checkpoint.json should be written"


def test_checkpoint_roundtrip_save_and_load(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    _loop(store).run(_build_state(), max_rounds=1)
    loaded = OptimizerCheckpoint.load(tmp_path / "checkpoint.json")
    assert loaded.round_index == 1
    assert "extraction" in loaded.active_prompts
    assert "analysis" in loaded.active_prompts
    assert len(loaded.sample_states) > 0


def test_checkpoint_schema_stable_keys(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    _loop(store).run(_build_state(), max_rounds=1)
    data = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    expected_keys = {"round_index", "active_prompts", "sample_states", "fewshot_pool_path", "metrics_summary", "created_at"}
    assert expected_keys.issubset(data.keys()), f"checkpoint should have keys: {expected_keys}, got {sorted(data.keys())}"
    assert "batch_accuracy" in data["metrics_summary"]
    assert "round_index" in data["metrics_summary"]


def test_resume_without_checkpoint_starts_from_beginning(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    loop = _loop(store, resume=True)
    # Should not raise; instead starts from the beginning since no checkpoint exists
    _, metrics, summary = loop.run(_build_state(), max_rounds=1)
    assert len(metrics) == 1
    assert summary.completed_round_count == 1


def test_resume_advances_round_index(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    state = _build_state()
    _, metrics1, _ = _loop(store).run(state, max_rounds=1)
    first_round_id = metrics1[0].round_id
    _, metrics2, summary2 = _loop(store, resume=True).run(state, max_rounds=1)
    second_round_id = metrics2[0].round_id
    assert second_round_id != first_round_id, "resumed run should use a higher round index"
    assert summary2.completed_round_count == 1


def test_default_resume_is_false_for_backward_compat(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    config = OptimizerConfig(batch_size=24)
    runner = RoundRunner(model_client=MockModelClient(), evaluator=Evaluator(), store=store, config=config)
    loop = OptimizerLoop(runner=runner, store=store, config=config)
    assert loop.resume is False


def test_run_smoke_cli_parses_resume_arg() -> None:
    import subprocess
    result = subprocess.run(["python", "-m", "mmap_optimizer.cli.main", "run-smoke", "--help"], capture_output=True, text=True, cwd=_project_root())
    assert result.returncode == 0
    assert "--resume" in result.stdout
