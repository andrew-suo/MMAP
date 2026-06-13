from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mmap_optimizer.core.scenario import (
    ScenarioValidationError,
    list_scenarios,
    load_scenario,
    stable_hash,
    validate_scenario,
    write_scenario_artifact_metadata,
)


def write_scenario(root: Path, scenario_id: str = "demo") -> Path:
    scenario = root / "scenarios" / scenario_id
    (scenario / "data").mkdir(parents=True)
    (scenario / "prompts").mkdir()
    (scenario / "schemas").mkdir()
    (root / "configs").mkdir()
    (root / "configs" / "optimizer.yaml").write_text(
        """
run_dir: runs/base
text_optimization:
  batch_size: 8
  max_rounds: 3
models:
  extraction:
    provider: mock
    model: base-extraction
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (scenario / "scenario.yaml").write_text(
        f"""
id: {scenario_id}
description: Demo scenario
task_type: qa
optimizer_config: optimizer.yaml
data_dir: data
prompts_dir: prompts
schemas_dir: schemas
schema_paths:
  - schemas/output.json
default_config:
  text_optimization:
    max_rounds: 1
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (scenario / "optimizer.yaml").write_text(
        """
run_dir: runs/scenario
text_optimization:
  batch_size: 4
models:
  extraction:
    model: scenario-extraction
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (scenario / "prompts" / "extraction.txt").write_text("Extract.\n", encoding="utf-8")
    (scenario / "prompts" / "analysis.txt").write_text("Analyze.\n", encoding="utf-8")
    (scenario / "schemas" / "output.json").write_text('{"type":"object"}\n', encoding="utf-8")
    (scenario / "data" / "samples.jsonl").write_text('{"id":"1"}\n', encoding="utf-8")
    return scenario


def test_scenario_config_inheritance_and_artifact_metadata(tmp_path: Path) -> None:
    write_scenario(tmp_path)

    scenario = load_scenario("demo", tmp_path / "scenarios", tmp_path / "configs" / "optimizer.yaml")

    assert scenario.id == "demo"
    assert scenario.optimizer_config.batch_size == 4
    assert scenario.optimizer_config.max_text_rounds == 1
    assert scenario.config_mapping["models"]["extraction"]["provider"] == "mock"
    assert scenario.config_mapping["models"]["extraction"]["model"] == "scenario-extraction"
    assert scenario.config_hash == stable_hash(scenario.config_mapping)
    assert scenario.artifact_metadata()["scenario_id"] == "demo"
    assert "extraction.txt" in scenario.prompt_hashes
    assert scenario.schema_hashes == {"schemas/output.json": scenario.schema_hashes["schemas/output.json"]}

    artifact_path = write_scenario_artifact_metadata(tmp_path / "run", scenario)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["scenario_id"] == "demo"
    assert artifact["scenario_config_hash"] == scenario.config_hash


def test_scenario_validation_reports_missing_schema(tmp_path: Path) -> None:
    scenario = write_scenario(tmp_path)
    (scenario / "schemas" / "output.json").unlink()

    with pytest.raises(ScenarioValidationError, match="schema path"):
        validate_scenario("demo", tmp_path / "scenarios")


def test_default_scenario_list_validate_and_cli_contracts() -> None:
    summaries = list_scenarios("scenarios")
    assert [summary.id for summary in summaries] == ["default"]

    scenario = load_scenario("default")
    assert scenario.data_dir.as_posix().endswith("scenarios/default/data")
    assert scenario.optimizer_config.scenario_id == "default"

    list_result = subprocess.run(
        [sys.executable, "-m", "mmap_optimizer.cli.main", "list-scenarios", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(list_result.stdout)[0]["id"] == "default"

    validate_result = subprocess.run(
        [sys.executable, "-m", "mmap_optimizer.cli.main", "validate-scenario", "default", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(validate_result.stdout)
    assert payload["valid"] is True
    assert payload["scenario_id"] == "default"
    assert payload["artifact_metadata"]["scenario_id"] == "default"


def test_python_module_entrypoint_reuses_main_cli() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mmap_optimizer", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "list-scenarios" in result.stdout
