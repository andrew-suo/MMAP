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
                "mock_prompt_outputs": [
                    {"contains": "当样本属于该错误模式时优先检查 NG 证据。", "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'}
                ],
            },
        ),
        Sample(
            id="s2",
            ground_truth_id="gt2",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_prompt_outputs": [
                    {"contains": "当样本属于该错误模式时优先检查 NG 证据。", "output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'}
                ],
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



def test_round_runner_rejects_toxic_temp_prompt_patch(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("raw extraction", PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    toxic_rule = "错误模式下强制输出 NG。"
    analysis_output = (
        '{'
        '"judgement":{"is_correct":false},'
        '"confirmed_facts":[],"hypothesized_error_causes":[],"prompt_section_attribution":[],'
        f'"patch_candidates":[{{"target_prompt":"extraction","target_section":"ambiguity_policy","operation":"ADD_RULE","intent":"toxic_ng","content":"{toxic_rule}","risk":"可能过严"}}]'
        '}'
    )
    samples = [
        Sample(
            id="s1",
            ground_truth_id="gt1",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_analysis_output": analysis_output,
                "mock_prompt_outputs": [
                    {"contains": toxic_rule, "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'}
                ],
            },
        ),
        Sample(
            id="s2",
            ground_truth_id="gt2",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_prompt_outputs": [
                    {"contains": toxic_rule, "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'}
                ],
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

    assert not round_record.accepted_patch_ids
    assert metrics.toxic_count == 1
    assert metrics.accepted_count == 0
    assert state.active_extraction_prompt.version == 1
    assert toxic_rule not in state.active_extraction_prompt.render().text


def test_round_runner_applies_all_patches_when_bundle_passes(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("raw extraction", PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    rule_a = "规则A：检查缺失标签。"
    rule_b = "规则B：检查安装方向。"
    analysis_output = (
        '{'
        '"judgement":{"is_correct":false},'
        '"confirmed_facts":[],"hypothesized_error_causes":[],"prompt_section_attribution":[],'
        f'"patch_candidates":['
        f'{{"target_prompt":"extraction","target_section":"ambiguity_policy","operation":"ADD_RULE","intent":"rule_a","content":"{rule_a}","risk":"low"}},'
        f'{{"target_prompt":"extraction","target_section":"visual_evidence_rules","operation":"ADD_RULE","intent":"rule_b","content":"{rule_b}","risk":"low"}}'
        ']}'
    )
    samples = [
        Sample(
            id="s1",
            ground_truth_id="gt1",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_analysis_output": analysis_output,
                "mock_prompt_outputs": [
                    {"contains": rule_a, "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                    {"contains": rule_b, "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                ],
            },
        ),
        Sample(
            id="s2",
            ground_truth_id="gt2",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_prompt_outputs": [
                    {"contains_all": [rule_a, rule_b], "output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                    {"contains": rule_a, "output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                    {"contains": rule_b, "output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                ],
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

    rendered = state.active_extraction_prompt.render().text
    assert len(round_record.accepted_patch_ids) == 2
    assert metrics.accepted_count == 2
    assert rule_a in rendered
    assert rule_b in rendered


def test_round_runner_uses_greedy_safe_subset_when_bundle_is_toxic(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("raw extraction", PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    safe_rule = "安全规则：检查缺失标签。"
    interaction_rule = "交互风险规则：检查安装方向。"
    analysis_output = (
        '{'
        '"judgement":{"is_correct":false},'
        '"confirmed_facts":[],"hypothesized_error_causes":[],"prompt_section_attribution":[],'
        f'"patch_candidates":['
        f'{{"target_prompt":"extraction","target_section":"ambiguity_policy","operation":"ADD_RULE","intent":"safe_rule","content":"{safe_rule}","risk":"low"}},'
        f'{{"target_prompt":"extraction","target_section":"visual_evidence_rules","operation":"ADD_RULE","intent":"interaction_rule","content":"{interaction_rule}","risk":"medium"}}'
        ']}'
    )
    samples = [
        Sample(
            id="s1",
            ground_truth_id="gt1",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_analysis_output": analysis_output,
                "mock_prompt_outputs": [
                    {"contains": safe_rule, "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                    {"contains": interaction_rule, "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                ],
            },
        ),
        Sample(
            id="s2",
            ground_truth_id="gt2",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_prompt_outputs": [
                    {"contains_all": [safe_rule, interaction_rule], "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                    {"contains": safe_rule, "output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                    {"contains": interaction_rule, "output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                ],
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

    rendered = state.active_extraction_prompt.render().text
    assert round_record.accepted_patch_ids == ["patch_round_000001_s1_00"]
    assert metrics.accepted_count == 1
    assert metrics.toxic_count >= 1
    assert safe_rule in rendered
    assert interaction_rule not in rendered


def test_schema_or_frozen_target_violation_promotes_analysis_schema_guard(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("raw extraction", PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    analysis_output = (
        '{'
        '"judgement":{"is_correct":false},'
        '"confirmed_facts":[],"hypothesized_error_causes":[],"prompt_section_attribution":[],'
        '"patch_candidates":[{"target_prompt":"extraction","target_section":"output_schema","operation":"ADD_RULE","intent":"bad_schema","content":"bad","risk":"high"}]'
        '}'
    )
    samples = [
        Sample(
            id="s1",
            ground_truth_id="gt1",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_analysis_output": analysis_output,
            },
        )
    ]
    gts = {"gt1": GroundTruth(id="gt1", sample_id="s1", value={"result": "NG"}, primary_answer="NG")}
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
        config=OptimizerConfig(batch_size=1, dynamic_validation_batch_size=0),
    )

    round_record, _ = runner.run_round(state, round_index=1)

    rendered_analysis = state.active_analysis_prompt.render().text
    assert round_record.analysis_evolution_report_id == "analysis_evolution_round_000001"
    assert state.active_analysis_prompt.version == 2
    assert "外部输出契约与 frozen section 不可作为 patch 目标" in rendered_analysis
    assert (tmp_path / "round_000001" / "reports" / "analysis_evolution_report.json").exists()


def test_toxic_patch_promotes_analysis_risk_policy(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("raw extraction", PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    toxic_rule = "风险规则：过度判定 NG。"
    analysis_output = (
        '{'
        '"judgement":{"is_correct":false},'
        '"confirmed_facts":[],"hypothesized_error_causes":[],"prompt_section_attribution":[],'
        f'"patch_candidates":[{{"target_prompt":"extraction","target_section":"ambiguity_policy","operation":"ADD_RULE","intent":"toxic_rule","content":"{toxic_rule}","risk":"medium"}}]'
        '}'
    )
    samples = [
        Sample(
            id="s1",
            ground_truth_id="gt1",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_analysis_output": analysis_output,
                "mock_prompt_outputs": [
                    {"contains": toxic_rule, "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'}
                ],
            },
        ),
        Sample(
            id="s2",
            ground_truth_id="gt2",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_prompt_outputs": [
                    {"contains": toxic_rule, "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'}
                ],
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

    rendered_analysis = state.active_analysis_prompt.render().text
    assert not round_record.accepted_patch_ids
    assert metrics.toxic_count >= 1
    assert state.active_analysis_prompt.version == 2
    assert "生成 patch 前必须说明它可能破坏的原正确样本类型" in rendered_analysis
