from pathlib import Path

from mmap_optimizer.core.config import OptimizerConfig
from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleState
from mmap_optimizer.evaluation.evaluator import Evaluator
from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.orchestration.optimizer_loop import OptimizerLoop
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


def test_round_runner_compresses_extraction_prompt_after_text_round(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    repeated_prompt = "保留关键审核规则。\n保留关键审核规则。\n保留关键审核规则。\n"
    extraction_prompt = initialize_prompt_version(repeated_prompt, PromptType.EXTRACTION, extraction_contract)
    before_lines = len(extraction_prompt.render().text.splitlines())
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    samples = [
        Sample(
            id="s1",
            ground_truth_id="gt1",
            metadata={"mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
        )
    ]
    gts = {"gt1": GroundTruth(id="gt1", sample_id="s1", value={"result": "OK"}, primary_answer="OK")}
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
        config=OptimizerConfig(batch_size=1, dynamic_validation_batch_size=0, extraction_line_budget=1),
    )

    round_record, metrics = runner.run_round(state, round_index=1)

    assert metrics.compression_triggered
    assert metrics.compression_accepted
    assert metrics.compression_line_reduction > 0
    assert state.active_extraction_prompt.version == 2
    assert state.active_extraction_prompt.version_type == "compression"
    assert len(state.active_extraction_prompt.render().text.splitlines()) < before_lines
    assert round_record.compression_report_ids == ["compression_round_000001_extraction"]
    report = JsonStore(tmp_path).read_json("round_000001/reports/compression_round_000001_extraction.json")
    assert report["accepted"] is True
    assert report["compressed_section_id"] == "legacy_unmapped"
    assert (tmp_path / "round_000001" / "runs" / "compression_runs.jsonl").exists()


def test_round_runner_rejects_compression_when_behavior_changes(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    raw_prompt = "触发 A。\n触发 A。\n"
    extraction_prompt = initialize_prompt_version(raw_prompt, PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    samples = [
        Sample(
            id="s1",
            ground_truth_id="gt1",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_prompt_outputs": [
                    {
                        "contains_all": ["触发 A。", "触发 A。\n触发 A。"],
                        "output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                    },
                    {
                        "contains": "触发 A。",
                        "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                    },
                ],
            },
        )
    ]
    gts = {"gt1": GroundTruth(id="gt1", sample_id="s1", value={"result": "OK"}, primary_answer="OK")}
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
        config=OptimizerConfig(batch_size=1, dynamic_validation_batch_size=0, extraction_line_budget=1),
    )

    round_record, metrics = runner.run_round(state, round_index=1)

    assert metrics.compression_triggered
    assert not metrics.compression_accepted
    assert state.active_extraction_prompt.version == 1
    assert round_record.compression_report_ids == ["compression_round_000001_extraction"]
    report = JsonStore(tmp_path).read_json("round_000001/reports/compression_round_000001_extraction.json")
    assert report["accepted"] is False
    assert report["failure_reason"] == "NO_SAFE_COMPRESSION_CANDIDATE"
    assert report["rejected_sections"][0]["reason"].startswith("PREDICTION_CHANGED")


def test_round_runner_adds_fewshot_after_text_rounds(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("stable extraction", PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    samples = [
        Sample(
            id="s1",
            ground_truth_id="gt1",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_prompt_outputs": [
                    {"contains": "FEW_SHOT_SAMPLE:s1", "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                ],
                "fewshot_reasoning": "示例说明：该样本存在应判定为 NG 的施工质量问题。",
            },
        ),
        Sample(id="s2", ground_truth_id="gt2", metadata={"mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'}),
    ]
    gts = {
        "gt1": GroundTruth(id="gt1", sample_id="s1", value={"result": "NG"}, primary_answer="NG"),
        "gt2": GroundTruth(id="gt2", sample_id="s2", value={"result": "OK"}, primary_answer="OK"),
    }
    state = OptimizerState(
        samples=samples,
        assets={},
        ground_truths=gts,
        sample_states={s.id: SampleState(sample_id=s.id, difficulty_ema=0.8) for s in samples},
        active_extraction_prompt=extraction_prompt,
        active_analysis_prompt=analysis_prompt,
        extraction_output_schema_contract=extraction_contract,
        analysis_output_schema_contract=analysis_contract,
    )
    runner = RoundRunner(
        model_client=MockModelClient(),
        evaluator=Evaluator(),
        store=JsonStore(tmp_path),
        config=OptimizerConfig(batch_size=2, dynamic_validation_batch_size=0, max_text_rounds=0, fewshot_enabled=True, fewshot_max_slots=2),
    )

    round_record, metrics = runner.run_round(state, round_index=1)

    assert metrics.fewshot_triggered
    assert metrics.fewshot_accepted
    assert metrics.fewshot_accuracy_delta == 0.5
    assert round_record.fewshot_report_ids == ["fewshot_round_000001_extraction"]
    rendered = state.active_extraction_prompt.render().text
    assert "FEW_SHOT_SAMPLE:s1" in rendered
    assert "示例说明：该样本存在应判定为 NG 的施工质量问题。" in rendered
    assert state.active_extraction_prompt.version_type == "few_shot_optimization"
    report = JsonStore(tmp_path).read_json("round_000001/reports/fewshot_round_000001_extraction.json")
    assert report["accepted"] is True
    assert report["selected_sample_id"] == "s1"
    assert (tmp_path / "round_000001" / "runs" / "fewshot_runs.jsonl").exists()


def test_round_runner_rejects_fewshot_when_it_breaks_correct_sample(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("stable extraction", PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    samples = [
        Sample(
            id="s1",
            ground_truth_id="gt1",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_prompt_outputs": [
                    {"contains": "FEW_SHOT_SAMPLE:s1", "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
                ],
            },
        ),
        Sample(
            id="s2",
            ground_truth_id="gt2",
            metadata={
                "mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}',
                "mock_prompt_outputs": [
                    {"contains": "FEW_SHOT_SAMPLE:s1", "output": '{"result":"NG","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'},
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
        config=OptimizerConfig(batch_size=2, dynamic_validation_batch_size=0, max_text_rounds=0, fewshot_enabled=True, fewshot_max_slots=1),
    )

    round_record, metrics = runner.run_round(state, round_index=1)

    assert metrics.fewshot_triggered
    assert not metrics.fewshot_accepted
    assert state.active_extraction_prompt.version == 1
    assert round_record.fewshot_report_ids == ["fewshot_round_000001_extraction"]
    report = JsonStore(tmp_path).read_json("round_000001/reports/fewshot_round_000001_extraction.json")
    assert report["accepted"] is False
    assert report["failure_reason"] == "NO_SAFE_FEWSHOT_CANDIDATE"
    assert report["rejected_candidates"][0]["broken_sample_ids"] == ["s2"]


def test_optimizer_loop_runs_configured_rounds_and_writes_summary(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("stable extraction", PromptType.EXTRACTION, extraction_contract)
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
    config = OptimizerConfig(batch_size=2, dynamic_validation_batch_size=0, max_text_rounds=2)
    store = JsonStore(tmp_path)
    runner = RoundRunner(model_client=MockModelClient(), evaluator=Evaluator(), store=store, config=config)

    rounds, metrics_records, summary = OptimizerLoop(runner=runner, store=store, config=config).run(state)

    assert [round_record.id for round_record in rounds] == ["round_000001", "round_000002"]
    assert len(metrics_records) == 2
    assert summary.status == "COMPLETED"
    assert summary.completed_round_count == 2
    assert summary.first_batch_accuracy == 0.5
    assert summary.final_batch_accuracy == 0.5
    assert summary.best_batch_accuracy == 0.5
    assert summary.total_rejected_patches >= 0
    persisted = JsonStore(tmp_path).read_json("run_summary.json")
    assert persisted["round_ids"] == ["round_000001", "round_000002"]
    assert persisted["final_extraction_prompt_version_id"] == state.active_extraction_prompt.id


class CountingMockClient(MockModelClient):
    def __init__(self, default_output='{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'):
        super().__init__(default_output=default_output)
        self.complete_calls = 0
        self.complete_multimodal_calls = 0
        self._inside_multimodal = False

    def complete(self, messages, model_config=None, response_format=None):
        if not self._inside_multimodal:
            self.complete_calls += 1
        return super().complete(messages, model_config, response_format)

    def complete_multimodal(self, messages, assets, model_config=None, response_format=None):
        self.complete_multimodal_calls += 1
        self._inside_multimodal = True
        try:
            return super().complete_multimodal(messages, assets, model_config, response_format)
        finally:
            self._inside_multimodal = False


def test_round_runner_uses_separate_extraction_and_optimizer_clients(tmp_path: Path):
    extraction_contract = contract(PromptType.EXTRACTION)
    analysis_contract = contract(PromptType.ANALYSIS)
    extraction_prompt = initialize_prompt_version("raw extraction", PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_version("raw analysis", PromptType.ANALYSIS, analysis_contract)
    samples = [
        Sample(id="s1", ground_truth_id="gt1", metadata={"mock_output": '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'}),
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
    extraction_client = CountingMockClient()
    optimizer_client = CountingMockClient(default_output='{"judgement":{"is_correct":false},"patch_candidates":[]}')
    runner = RoundRunner(
        extraction_client=extraction_client,
        optimizer_client=optimizer_client,
        evaluator=Evaluator(),
        store=JsonStore(tmp_path),
        config=OptimizerConfig(batch_size=1, dynamic_validation_batch_size=0),
    )

    runner.run_round(state, round_index=1)

    assert extraction_client.complete_multimodal_calls >= 1
    assert extraction_client.complete_calls == 0
    assert optimizer_client.complete_calls == 1
    assert optimizer_client.complete_multimodal_calls == 0
