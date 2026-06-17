import json
from pathlib import Path

import pytest

from mmap_optimizer.config import ExecutionConfig, execution_config_from_mapping, validate_optimizer_config_mapping
from mmap_optimizer.core.scenario import load_scenario
from mmap_optimizer.orchestration.executor import SampleExecutor, map_ordered
from mmap_optimizer.prompt.health import check_prompt_health, safe_autofix_prompt_ir
from mmap_optimizer.prompt.ir import PromptIR, PromptSection


def test_execution_config_and_executor_retry_failed_samples():
    config = execution_config_from_mapping({"mode": "thread_pool", "max_workers": 2, "retry_attempts": 1})
    assert config == ExecutionConfig(mode="thread_pool", max_workers=2, retry_attempts=1)
    seen = {"a": 0}

    def task(sample):
        if sample["sample_id"] == "a" and seen["a"] == 0:
            seen["a"] += 1
            raise ValueError("transient")
        return sample["value"] * 2

    outcomes = SampleExecutor(config).map(
        [{"sample_id": "a", "value": 2}, {"sample_id": "b", "value": 3}], task, sort_by_sample_id=True
    )

    assert [outcome.ok for outcome in outcomes] == [True, True]
    assert [outcome.value for outcome in outcomes] == [4, 6]
    assert outcomes[0].attempt_count == 2
    assert map_ordered([1, 2, 3], lambda value: value + 1, max_workers=2) == [2, 3, 4]


def test_config_validation_reports_invalid_execution_settings():
    errors = validate_optimizer_config_mapping({"execution": {"max_workers": 0}})
    assert errors
    assert any("CONFIG_PARSE_ERROR" in error or "execution.max_workers" in error for error in errors)


def test_scenario_manifest_can_override_directory_names(tmp_path: Path):
    (tmp_path / "scenario.yaml").write_text(
        "optimizer_config: custom_optimizer.yaml\ndata_dir: fixtures\nprompts_dir: prompt_files\nschemas_dir: schema_files\n",
        encoding="utf-8",
    )
    (tmp_path / "custom_optimizer.yaml").write_text("run_dir: runs\n", encoding="utf-8")

    scenario = load_scenario(tmp_path)

    assert scenario.data_dir == tmp_path / "fixtures"
    assert scenario.prompts_dir == tmp_path / "prompt_files"
    assert scenario.schemas_dir == tmp_path / "schema_files"
    assert scenario.manifest["optimizer_config"] == "custom_optimizer.yaml"


def test_prompt_health_safe_autofix_freezes_schema_section():
    prompt_ir = PromptIR(
        id="prompt_ir",
        prompt_type="extraction",
        version=1,
        output_schema_contract_id="schema",
        sections=[
            PromptSection(id="output_schema", type="schema", content='{"type":"object"}', mutability="normal"),
        ],
        rendering_order=["output_schema"],
    )

    assert not check_prompt_health(prompt_ir).ok
    fixed = safe_autofix_prompt_ir(prompt_ir)
    assert check_prompt_health(fixed).ok
    assert fixed.section_by_id("output_schema").mutability == "frozen"
    assert fixed.section_by_id("output_schema").compressibility == "none"

from mmap_optimizer.compression.report import CompressionReport
from mmap_optimizer.compression.semantic import check_output_constraints


def test_semantic_output_constraints_and_report_fields():
    check = check_output_constraints("answer\nwith citation", required_terms=["citation"], forbidden_terms=["forbidden"], max_lines=3)
    assert check.valid
    failing = check_output_constraints("answer", required_terms=["citation"], max_lines=0)
    assert not failing.valid
    report = CompressionReport(
        id="c1",
        round_id="r1",
        prompt_type="extraction",
        prompt_version_before_id="p1",
        triggered=True,
        reason="budget",
    )
    assert report.triggered
