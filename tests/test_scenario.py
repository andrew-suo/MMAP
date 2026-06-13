from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmap_optimizer.cli import main
from mmap_optimizer.core.scenario import ScenarioConfig


def write_scenario(root: Path, *, include_schema: bool = True) -> Path:
    scenario = root / "foo"
    (scenario / "prompts").mkdir(parents=True)
    (scenario / "schemas").mkdir(parents=True)
    (scenario / "data").mkdir(parents=True)
    (scenario / "optimizer.yaml").write_text(
        """
model:
  name: custom-model
sampling:
  temperature: 0.7
compression:
  enabled: true
fewshot:
  enabled: true
  examples:
    - one
patch_merge:
  strategy: squash
run_dir: runs/from-scenario
""".lstrip(),
        encoding="utf-8",
    )
    (scenario / "prompts" / "system.md").write_text("Optimize this.\n", encoding="utf-8")
    (scenario / "data" / "case.json").write_text('{"case": 1}\n', encoding="utf-8")
    if include_schema:
        (scenario / "schemas" / "output.json").write_text(
            '{"type": "object", "properties": {"ok": {"type": "boolean"}}}\n',
            encoding="utf-8",
        )
    return scenario


def test_loads_default_scenario() -> None:
    scenario = ScenarioConfig.load("scenarios/default")

    assert scenario.scenario_id == "default"
    assert scenario.optimizer_config["model"]["name"] == "gpt-5.5"
    assert "system.md" in scenario.prompts
    assert "output.json" in scenario.schemas
    assert scenario.artifact_metadata() == {
        "scenario_id": "default",
        "scenario_config_hash": scenario.config_hash,
    }


def test_cli_run_dir_override_writes_artifact(tmp_path: Path) -> None:
    scenario_dir = write_scenario(tmp_path / "scenarios")
    run_dir = tmp_path / "custom-run"

    exit_code = main(["--scenario", str(scenario_dir), "--run-dir", str(run_dir)])

    artifact = json.loads((run_dir / "artifact.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert artifact["scenario_id"] == "foo"
    assert artifact["optimizer_config"]["run_dir"] == str(run_dir)
    assert artifact["resources"]["schemas"] == ["output.json"]


def test_missing_schema_raises(tmp_path: Path) -> None:
    scenario_dir = write_scenario(tmp_path / "scenarios", include_schema=False)

    with pytest.raises(FileNotFoundError, match="no schema files"):
        ScenarioConfig.load(scenario_dir)


def test_scenario_config_hash_is_stable(tmp_path: Path) -> None:
    scenario_dir = write_scenario(tmp_path / "scenarios")

    first = ScenarioConfig.load(scenario_dir)
    second = ScenarioConfig.load(scenario_dir)
    run_dir_override = first.with_run_dir(tmp_path / "other-run")

    assert first.config_hash == second.config_hash
    assert first.config_hash == run_dir_override.config_hash
    assert len(first.config_hash) == 64
