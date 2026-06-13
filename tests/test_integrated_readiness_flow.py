from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmap_optimizer.cli.main import main as cli_main
from mmap_optimizer.core.config import OptimizerConfig, optimizer_config_from_mapping
from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleState
from mmap_optimizer.evaluation.evaluator import Evaluator, normalize_label
from mmap_optimizer.model.client import MockModelClient, ModelResponse
from mmap_optimizer.orchestration.round_runner import OptimizerState, RoundRunner
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.initializer import initialize_prompt_version
from mmap_optimizer.storage.json_store import JsonStore
from mmap_optimizer.testing.prompt_test_runner import PromptTestRunner


def contract(prompt_type: PromptType = PromptType.EXTRACTION) -> OutputSchemaContract:
    return OutputSchemaContract(
        id=f"{prompt_type.value}_contract",
        prompt_type=prompt_type,
        version=1,
        schema={
            "type": "object",
            "required": ["result", "confidence", "evidence", "used_prompt_sections"],
            "properties": {
                "result": {"type": "string"},
                "confidence": {"type": "number"},
                "evidence": {"type": "array"},
                "used_prompt_sections": {"type": "array"},
            },
            "x-primary-answer-fields": ["result"],
        },
        primary_answer_fields=["result"],
    )


class SequenceClient(MockModelClient):
    def __init__(self, outputs: list[str]):
        super().__init__()
        self.outputs = outputs
        self.index = 0

    def complete(self, messages, model_config=None, response_format=None):
        output = self.outputs[min(self.index, len(self.outputs) - 1)]
        self.index += 1
        return ModelResponse(raw_output=output)


def test_prompt_runner_uses_no_gt_voting_and_keeps_order():
    prompt = initialize_prompt_version("raw extraction", PromptType.EXTRACTION, contract())
    samples = [Sample(id="s1", ground_truth_id="missing")]
    outputs = [
        '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
        '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
        '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
    ]
    result = PromptTestRunner(
        model_client=SequenceClient(outputs),
        evaluator=Evaluator(),
        max_workers=2,
        vote_rounds=3,
        enable_voting=True,
    ).run(
        round_id="round_1",
        run_type="extraction",
        prompt=prompt,
        samples=samples,
        assets={},
        ground_truths={},
        contract=contract(),
    )
    assert result.runs[0].sample_id == "s1"
    assert result.evaluations[0].ground_truth_id == "NO_GT"
    assert result.evaluations[0].extra["vote_majority"] == "OK"
    assert result.evaluations[0].extra["vote_confidence"] == pytest.approx(2 / 3)


def test_round_runner_health_check_aborts_on_error(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("raw extraction", PromptType.EXTRACTION, extraction_contract)
    extraction_prompt.prompt_ir.section_by_id("output_schema").compressibility = "medium"
    state = OptimizerState(
        samples=[],
        assets={},
        ground_truths={},
        sample_states={},
        active_extraction_prompt=extraction_prompt,
        active_analysis_prompt=initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract),
        extraction_output_schema_contract=extraction_contract,
        analysis_output_schema_contract=analysis_contract,
    )
    runner = RoundRunner(
        model_client=MockModelClient(),
        evaluator=Evaluator(),
        store=JsonStore(tmp_path),
        config=OptimizerConfig(prompt_health_check_enabled=True),
    )
    with pytest.raises(ValueError, match="EXTRACTION_PROMPT_HEALTH_ERROR"):
        runner.run_round(state, round_index=1)
    assert (tmp_path / "round_000001" / "health" / "extraction_prompt_health.json").exists()


def test_round_runner_saves_snapshot_before_promoting_patch(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("raw extraction", PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    patch_text = "优先检查 NG 证据。"
    analysis_output = json.dumps(
        {
            "judgement": {"is_correct": False},
            "confirmed_facts": [],
            "hypothesized_error_causes": [],
            "prompt_section_attribution": [],
            "patch_candidates": [
                {
                    "target_prompt": "extraction",
                    "target_section": "ambiguity_policy",
                    "operation": "ADD_RULE",
                    "intent": "fix_ng",
                    "content": patch_text,
                    "risk": "low",
                }
            ],
        }
    )
    samples = [
        Sample(
            id="s1",
            ground_truth_id="gt1",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_analysis_output": analysis_output,
                "mock_prompt_outputs": [
                    {"contains": patch_text, "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                ],
            },
        )
    ]
    state = OptimizerState(
        samples=samples,
        assets={},
        ground_truths={"gt1": GroundTruth(id="gt1", sample_id="s1", value={"result": "NG"}, primary_answer="NG")},
        sample_states={"s1": SampleState(sample_id="s1")},
        active_extraction_prompt=extraction_prompt,
        active_analysis_prompt=analysis_prompt,
        extraction_output_schema_contract=extraction_contract,
        analysis_output_schema_contract=analysis_contract,
    )
    runner = RoundRunner(
        model_client=MockModelClient(),
        evaluator=Evaluator(),
        store=JsonStore(tmp_path),
        config=OptimizerConfig(batch_size=1, dynamic_validation_batch_size=0, prompt_snapshot_enabled=True),
    )
    round_record, _ = runner.run_round(state, round_index=1)
    assert round_record.accepted_patch_ids
    assert list((tmp_path / "snapshots").glob("*.json"))


def test_scenario_mapping_and_cli_check_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    scenario = tmp_path / "table_extraction"
    (scenario / "prompts").mkdir(parents=True)
    (scenario / "schemas").mkdir()
    (scenario / "data").mkdir()
    (scenario / "optimizer.yaml").write_text("run_dir: runs\n", encoding="utf-8")
    (scenario / "prompts" / "extraction.txt").write_text("extract", encoding="utf-8")
    (scenario / "prompts" / "analysis.txt").write_text("analysis", encoding="utf-8")
    schema = {
        "type": "object",
        "required": ["result"],
        "properties": {"result": {"type": "string"}},
        "x-primary-answer-fields": ["result"],
    }
    (scenario / "schemas" / "extraction_output_schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (scenario / "schemas" / "analysis_output_schema.json").write_text(json.dumps(schema), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["mmap", "check-prompt", "--scenario", str(scenario)])
    cli_main()
    assert "extraction" in capsys.readouterr().out


def test_config_parses_integrated_feature_flags():
    config = optimizer_config_from_mapping(
        {
            "patch_repair": {"enabled": True, "max_attempts": 2},
            "execution": {"max_workers": 4},
            "evaluation": {"voting_enabled": True, "vote_rounds": 5},
            "contribution": {"feedback_enabled": False},
            "scenario_id": "cabinet_cable",
        }
    )
    assert config.patch_repair_enabled is True
    assert config.patch_repair_max_attempts == 2
    assert config.execution_max_workers == 4
    assert config.eval_vote_rounds == 5
    assert config.contribution_feedback_enabled is False
    assert config.scenario_id == "cabinet_cable"


@pytest.mark.parametrize(
    "value,expected",
    [("合格", "OK"), ("正常", "OK"), ("不合格", "NG"), ("异常", "NG"), ("无法确认", "UNCERTAIN"), ("custom", "CUSTOM")],
)
def test_label_normalization_matrix(value: str, expected: str):
    assert normalize_label(value) == expected

@pytest.mark.parametrize("case_index", range(240))
def test_broad_regression_matrix_for_config_and_labels(case_index: int):
    max_workers = (case_index % 8) + 1
    vote_rounds = 3 + (case_index % 3) * 2
    config = optimizer_config_from_mapping(
        {
            "execution": {"max_workers": max_workers},
            "evaluation": {"voting_enabled": case_index % 2 == 0, "vote_rounds": vote_rounds},
            "patch_repair": {"enabled": case_index % 5 == 0, "max_attempts": 1 + (case_index % 3)},
        }
    )
    assert config.execution_max_workers == max_workers
    assert config.eval_vote_rounds == vote_rounds
    assert config.patch_repair_max_attempts in {1, 2, 3}
    assert normalize_label("合格" if case_index % 2 == 0 else "不合格") in {"OK", "NG"}
