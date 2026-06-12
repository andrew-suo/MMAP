from pathlib import Path

from mmap_optimizer.core.config import OptimizerConfig
from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleState
from mmap_optimizer.evaluation.evaluator import Evaluator
from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.orchestration.round_runner import OptimizerState, RoundRunner
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.validator import PatchValidator
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.initializer import initialize_prompt_version
from mmap_optimizer.storage.json_store import JsonStore


def contract(prompt_type=PromptType.EXTRACTION):
    return OutputSchemaContract(
        id=f"{prompt_type.value}_schema_v1",
        prompt_type=prompt_type,
        version=1,
        primary_answer_fields=["result"],
        schema={
            "type": "object",
            "required": ["result", "confidence", "evidence", "used_prompt_sections"],
            "properties": {
                "result": {"type": "string", "enum": ["OK", "NG", "UNCERTAIN"]},
                "confidence": {"type": "number"},
                "evidence": {"type": "array"},
                "used_prompt_sections": {"type": "array"},
            },
        },
    )


def test_patch_validator_rejects_frozen_output_schema():
    prompt = initialize_prompt_version("raw", PromptType.EXTRACTION, contract())
    patch = Patch(
        id="p1",
        type="prompt_patch",
        status="draft",
        target_prompt_type="extraction",
        base_version_id=prompt.id,
        section_id="output_schema",
        operation_type="ADD_RULE",
        operation_mode="append",
        intent_name="bad",
        intent_description="bad",
        patch_text="新增字段 reason",
        rationale="bad",
        source_sample_ids=["s1"],
    )

    result = PatchValidator().validate(patch, prompt.prompt_ir)

    assert not result.valid
    assert result.reason == "TARGET_SECTION_FROZEN"


def test_round_runner_writes_metrics(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("raw extraction", PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    samples = [
        Sample(id="s1", ground_truth_id="gt1", metadata={"mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'}),
        Sample(id="s2", ground_truth_id="gt2", metadata={"mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'}),
    ]
    gts = {
        "gt1": GroundTruth(id="gt1", sample_id="s1", value={"result": "OK"}, primary_answer="OK"),
        "gt2": GroundTruth(id="gt2", sample_id="s2", value={"result": "NG"}, primary_answer="NG"),
    }
    state = OptimizerState(
        samples=samples,
        assets={},
        ground_truths=gts,
        sample_states={s.id: SampleState(sample_id=s.id) for s in samples},
        active_extraction_prompt=extraction_prompt,
        active_analysis_prompt=analysis_prompt,
        extraction_output_schema_contract=extraction_contract,
        analysis_output_schema_contract=analysis_contract,
    )
    runner = RoundRunner(
        model_client=MockModelClient(),
        evaluator=Evaluator(),
        store=JsonStore(tmp_path),
        config=OptimizerConfig(batch_size=2, dynamic_validation_batch_size=0),
    )

    round_record, metrics = runner.run_round(state, round_index=1)

    assert round_record.status == "ROUND_COMPLETED"
    assert metrics.batch_accuracy == 0.5
    assert (tmp_path / "round_000001" / "metrics" / "round_metrics.json").exists()


def test_round_runner_accepts_analysis_patch_and_updates_prompt(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("raw extraction", PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    analysis_output = (
        '{'
        '"judgement":{"is_correct":false},'
        '"confirmed_facts":[],"hypothesized_error_causes":[],"prompt_section_attribution":[],'
        '"patch_candidates":[{"target_prompt":"extraction","target_section":"ambiguity_policy","operation":"ADD_RULE","intent":"fix_ng","content":"当样本属于该错误模式时优先检查 NG 证据。","risk":"可能过严"}]'
        '}'
    )
    samples = [
        Sample(
            id="s1",
            ground_truth_id="gt1",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_analysis_output": analysis_output,
                "mock_patch_outputs": {
                    "ambiguity_policy": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'
                },
            },
        ),
        Sample(
            id="s2",
            ground_truth_id="gt2",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_patch_outputs": {
                    "ambiguity_policy": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'
                },
            },
        ),
    ]
    gts = {
        "gt1": GroundTruth(id="gt1", sample_id="s1", value={"result": "NG"}, primary_answer="NG"),
        "gt2": GroundTruth(id="gt2", sample_id="s2", value={"result": "OK"}, primary_answer="OK"),
    }
    state = OptimizerState(
        samples=samples,
        assets={},
        ground_truths=gts,
        sample_states={s.id: SampleState(sample_id=s.id) for s in samples},
        active_extraction_prompt=extraction_prompt,
        active_analysis_prompt=analysis_prompt,
        extraction_output_schema_contract=extraction_contract,
        analysis_output_schema_contract=analysis_contract,
    )
    runner = RoundRunner(
        model_client=MockModelClient(),
        evaluator=Evaluator(),
        store=JsonStore(tmp_path),
        config=OptimizerConfig(batch_size=2, dynamic_validation_batch_size=0),
    )

    round_record, metrics = runner.run_round(state, round_index=1)

    assert round_record.accepted_patch_ids
    assert metrics.accepted_count == 1
    assert state.active_extraction_prompt.version == 2
    rendered = state.active_extraction_prompt.render().text
    assert "当样本属于该错误模式时优先检查 NG 证据。" in rendered
    assert (tmp_path / "round_000001" / "patches" / "patch_test_results.jsonl").exists()
