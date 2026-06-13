from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mmap_optimizer.core.scenario import (
    ScenarioValidationError,
    load_scenario,
    stable_hash,
    validate_scenario,
    write_run_artifacts,
)


def write_scenario(root: Path, scenario_id: str = "demo") -> Path:
    scenario = root / "scenarios" / scenario_id
    (scenario / "data").mkdir(parents=True)
    (scenario / "prompts").mkdir()
    (scenario / "schemas").mkdir()
    (root / "configs").mkdir()
    (root / "configs" / "optimizer.yaml").write_text(
        """
model: base-model
limits:
  retries: 1
  timeout: 30
features:
  tracing: false
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (scenario / "scenario.yaml").write_text(
        """
id: demo
description: Demo scenario
task_type: qa
schema_paths:
  - schemas/input.json
default_config:
  limits:
    timeout: 10
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (scenario / "optimizer.yaml").write_text(
        """
model: scenario-model
limits:
  retries: 3
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (scenario / "README.md").write_text("# Demo\n", encoding="utf-8")
    (scenario / "prompts" / "system.txt").write_text("Be helpful.\n", encoding="utf-8")
    (scenario / "schemas" / "input.json").write_text('{"type":"object"}\n', encoding="utf-8")
    return scenario


def test_missing_file_reports_error(tmp_path: Path) -> None:
    scenario = write_scenario(tmp_path)
    (scenario / "README.md").unlink()

    with pytest.raises(ScenarioValidationError, match="README.md"):
        validate_scenario("demo", tmp_path / "scenarios")


def test_base_config_inheritance_and_override(tmp_path: Path) -> None:
    write_scenario(tmp_path)

    scenario = load_scenario("demo", tmp_path / "scenarios", tmp_path / "configs" / "optimizer.yaml")

    assert scenario.config == {
        "model": "scenario-model",
        "limits": {"retries": 3, "timeout": 10},
        "features": {"tracing": False},
    }


def test_hashes_are_stable_and_artifacts_include_scenario_metadata(tmp_path: Path) -> None:
    write_scenario(tmp_path)

    first = load_scenario("demo", tmp_path / "scenarios", tmp_path / "configs" / "optimizer.yaml")
    second = load_scenario("demo", tmp_path / "scenarios", tmp_path / "configs" / "optimizer.yaml")

    assert first.config_hash == second.config_hash == stable_hash(first.config)
    assert first.prompt_hashes == second.prompt_hashes
    assert first.schema_hashes == second.schema_hashes

    artifact_path = write_run_artifacts(tmp_path / "runs" / "1", first)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["scenario_id"] == "demo"
    assert artifact["scenario_config_hash"] == first.config_hash
    assert artifact["prompt_hashes"] == dict(first.prompt_hashes)
    assert artifact["schema_hashes"] == dict(first.schema_hashes)


def test_cli_list_and_validate(tmp_path: Path) -> None:
    write_scenario(tmp_path)

    list_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mmap_optimizer.cli",
            "list-scenarios",
            "--scenarios-dir",
            str(tmp_path / "scenarios"),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    listed = json.loads(list_result.stdout)
    assert listed[0]["id"] == "demo"

    validate_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mmap_optimizer.cli",
            "validate-scenario",
            "demo",
            "--scenarios-dir",
            str(tmp_path / "scenarios"),
            "--base-config",
            str(tmp_path / "configs" / "optimizer.yaml"),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(validate_result.stdout)
    assert payload["valid"] is True
    assert payload["scenario_id"] == "demo"
    assert payload["config"]["limits"] == {"retries": 3, "timeout": 10}
