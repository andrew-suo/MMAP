"""PR1 集成验证测试：真实 executor 链路。

验证 4 个真实 executor（ExtractionExecutor、EvaluationExecutor、
AnalysisExecutor、FewshotExecutor）通过 MockModelClient 产出真实的
correct/wrong/invalid 评估结果，并验证 factory 在 model_client 可用时
返回真实 executor、无 model_client 时返回 Mock executor。

本测试不连接真实模型，全部使用 ``MockModelClient`` 作为 ModelClient 替身。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.executors.analysis_executor import AnalysisExecutor
from mmap_optimizer.executors.evaluation_executor import EvaluationExecutor
from mmap_optimizer.executors.extraction_executor import ExtractionExecutor
from mmap_optimizer.executors.factory import (
    _MockAnalysisExecutor,
    _MockEvaluationExecutor,
    _MockExtractionExecutor,
    _MockFewshotExecutor,
    create_executors,
)
from mmap_optimizer.executors.fewshot_executor import FewshotExecutor
from mmap_optimizer.stages.extraction_prompt_optimization import (
    AnalysisResult,
    EvalRecord,
    ExtractionResult,
)
from mmap_optimizer.data.sample import (
    SampleBatch,
    SampleSet,
    SampleSpec,
    SampleState,
)
from mmap_optimizer.prompt.structured_prompt import (
    PromptSection,
    StructuredPrompt,
)


# ---------------------------------------------------------------------------
# 测试辅助构造函数
# ---------------------------------------------------------------------------


def make_extraction_prompt() -> StructuredPrompt:
    """构造测试用 extraction StructuredPrompt。"""
    sections = [
        PromptSection(
            id="section_1",
            title="Task",
            level=1,
            content="Extract the result from the image.",
            mutable=True,
        ),
        PromptSection(
            id="section_2",
            title="Output Schema",
            level=1,
            content='{"result": "string"}',
            mutable=False,
        ),
    ]
    return StructuredPrompt(
        id="test_extraction_prompt",
        prompt_type="extraction",
        sections=sections,
        raw_markdown="# Task\n\nExtract the result from the image.\n\n# Output Schema\n\n"
        '{"result": "string"}',
    )


def make_analysis_prompt() -> StructuredPrompt:
    """构造测试用 analysis StructuredPrompt。"""
    sections = [
        PromptSection(
            id="section_1",
            title="Analysis Task",
            level=1,
            content="Analyze whether the extraction result is correct.",
            mutable=True,
        ),
    ]
    return StructuredPrompt(
        id="test_analysis_prompt",
        prompt_type="analysis",
        sections=sections,
        raw_markdown="# Analysis Task\n\nAnalyze whether the extraction result is correct.",
    )


def make_sample_set(ground_truth: dict[str, Any]) -> tuple[SampleSet, SampleBatch]:
    """构造测试用 SampleSet 和 SampleBatch。

    返回 (sample_set, batch)，包含 1 个样本。
    """
    spec = SampleSpec(
        id="sample_1",
        input={"text": "Sample text"},
        ground_truth=ground_truth,
    )
    state = SampleState(sample_id="sample_1")
    sample_set = SampleSet(specs={"sample_1": spec}, states={"sample_1": state})
    batch = SampleBatch(
        id="batch_1",
        phase="prompt_optimization",
        iteration=1,
        sample_ids=["sample_1"],
        sampler_name="test",
    )
    return sample_set, batch


# ---------------------------------------------------------------------------
# SubTask 10.1: ExtractionExecutor + EvaluationExecutor 产出真实 correct/wrong/invalid
# ---------------------------------------------------------------------------


def test_extraction_and_evaluation_produce_correct():
    """测试 1：ExtractionExecutor + EvaluationExecutor 产出 correct。

    MockModelClient 默认返回 {"result":"OK",...}，ground_truth={"result":"OK"}，
    字段级 exact match 应判定为 correct。
    """
    prompt = make_extraction_prompt()
    sample_set, batch = make_sample_set(ground_truth={"result": "OK"})

    client = MockModelClient()  # default_output 含 "result":"OK"
    extraction_executor = ExtractionExecutor(client)
    evaluation_executor = EvaluationExecutor()

    extraction_results = extraction_executor.execute(prompt, batch, sample_set)
    assert len(extraction_results) == 1
    er = extraction_results[0]
    assert er.sample_id == "sample_1"
    assert er.status == "correct", f"expected correct, got {er.status}"
    assert isinstance(er.parsed_output, dict)
    assert er.parsed_output.get("result") == "OK"

    eval_records = evaluation_executor.evaluate_batch(extraction_results, sample_set)
    assert len(eval_records) == 1
    record = eval_records[0]
    assert record.status == "correct", f"expected correct, got {record.status}"
    assert record.correct is True


def test_extraction_and_evaluation_produce_wrong():
    """测试 2：ExtractionExecutor + EvaluationExecutor 产出 wrong。

    MockModelClient 返回 {"result":"OK",...}，但 ground_truth={"result":"WRONG_ANSWER"}，
    字段不匹配应判定为 wrong。
    """
    prompt = make_extraction_prompt()
    sample_set, batch = make_sample_set(ground_truth={"result": "WRONG_ANSWER"})

    client = MockModelClient()  # default_output 含 "result":"OK"
    extraction_executor = ExtractionExecutor(client)
    evaluation_executor = EvaluationExecutor()

    extraction_results = extraction_executor.execute(prompt, batch, sample_set)
    assert len(extraction_results) == 1
    er = extraction_results[0]
    # 解析成功，status 仍为 correct（解析层面）
    assert er.status == "correct"
    assert er.parsed_output.get("result") == "OK"

    eval_records = evaluation_executor.evaluate_batch(extraction_results, sample_set)
    assert len(eval_records) == 1
    record = eval_records[0]
    assert record.status == "wrong", f"expected wrong, got {record.status}"
    assert record.correct is False
    # details 应包含 mismatched_fields
    assert "result" in record.details.get("mismatched_fields", [])


def test_extraction_and_evaluation_produce_invalid():
    """测试 3：ExtractionExecutor + EvaluationExecutor 产出 invalid。

    MockModelClient 返回非 JSON 字符串，ExtractionResult.status 应为 invalid，
    parsed_output 为 None；EvalRecord.status 也应为 invalid。
    """
    prompt = make_extraction_prompt()
    sample_set, batch = make_sample_set(ground_truth={"result": "OK"})

    client_invalid = MockModelClient(default_output="not a json")
    extraction_executor = ExtractionExecutor(client_invalid)
    evaluation_executor = EvaluationExecutor()

    extraction_results = extraction_executor.execute(prompt, batch, sample_set)
    assert len(extraction_results) == 1
    er = extraction_results[0]
    assert er.status == "invalid", f"expected invalid, got {er.status}"
    assert er.parsed_output is None

    eval_records = evaluation_executor.evaluate_batch(extraction_results, sample_set)
    assert len(eval_records) == 1
    record = eval_records[0]
    assert record.status == "invalid", f"expected invalid, got {record.status}"
    assert record.correct is False


def test_sample_state_updated_by_real_evaluation():
    """测试 4：SampleState 基于真实评估更新 error_ema 和 difficulty_score。

    correct 样本：error_ema 应保持低值（0.0）。
    wrong 样本：error_ema 应升高（0.3，因为 alpha=0.3，初始 0.0）。
    """
    prompt = make_extraction_prompt()

    # correct 样本
    sample_set_ok, batch_ok = make_sample_set(ground_truth={"result": "OK"})
    client_ok = MockModelClient()
    executor_ok = ExtractionExecutor(client_ok)
    evaluator_ok = EvaluationExecutor()
    results_ok = executor_ok.execute(prompt, batch_ok, sample_set_ok)
    evaluator_ok.evaluate_batch(results_ok, sample_set_ok)
    state_ok = sample_set_ok.states["sample_1"]
    assert state_ok.error_ema == 0.0, f"correct 样本 error_ema 应为 0.0, got {state_ok.error_ema}"
    assert state_ok.difficulty_score == 0.0
    assert state_ok.last_extraction_status == "correct"

    # wrong 样本
    sample_set_wrong, batch_wrong = make_sample_set(ground_truth={"result": "WRONG_ANSWER"})
    client_wrong = MockModelClient()
    executor_wrong = ExtractionExecutor(client_wrong)
    evaluator_wrong = EvaluationExecutor()
    results_wrong = executor_wrong.execute(prompt, batch_wrong, sample_set_wrong)
    evaluator_wrong.evaluate_batch(results_wrong, sample_set_wrong)
    state_wrong = sample_set_wrong.states["sample_1"]
    # alpha=0.3, error_signal=1, 初始 0.0 → 0.3*1 + 0.7*0 = 0.3
    assert state_wrong.error_ema == 0.3, (
        f"wrong 样本 error_ema 应为 0.3, got {state_wrong.error_ema}"
    )
    assert state_wrong.difficulty_score == 0.3
    assert state_wrong.last_extraction_status == "wrong"
    assert state_wrong.error_count == 1

    # 验证 wrong 的 error_ema 高于 correct
    assert state_wrong.error_ema > state_ok.error_ema


def test_mock_and_real_evaluation_align_on_state_semantics_for_wrong_sample():
    """测试：mock / real evaluation 对错误样本的状态语义保持一致。"""
    prompt = make_extraction_prompt()

    sample_set_real, batch_real = make_sample_set(ground_truth={"result": "WRONG_ANSWER"})
    real_client = MockModelClient()
    real_extraction = ExtractionExecutor(real_client)
    real_evaluation = EvaluationExecutor()
    real_results = real_extraction.execute(prompt, batch_real, sample_set_real)
    real_evaluation.evaluate_batch(real_results, sample_set_real)
    real_state = sample_set_real.states["sample_1"]

    sample_set_mock, batch_mock = make_sample_set(ground_truth={"result": "IGNORED"})
    mock_extraction = _MockExtractionExecutor()
    mock_evaluation = _MockEvaluationExecutor()
    mock_results = mock_extraction.execute(prompt, batch_mock, sample_set_mock)
    mock_results[0].status = "wrong"
    mock_evaluation.evaluate_batch(mock_results, sample_set_mock)
    mock_state = sample_set_mock.states["sample_1"]

    assert real_state.last_extraction_status == "wrong"
    assert mock_state.last_extraction_status == "wrong"
    assert real_state.error_count == 1
    assert mock_state.error_count == 1
    assert real_state.error_ema == mock_state.error_ema == 0.3
    assert real_state.difficulty_score == mock_state.difficulty_score == 0.3


def test_mock_evaluation_derives_wrong_from_content_mismatch():
    """测试：mock evaluation 也应基于内容比对得出 wrong，而非信任 extraction status。"""
    sample_set, _ = make_sample_set(ground_truth={"result": "WRONG_ANSWER"})
    mock_evaluation = _MockEvaluationExecutor()
    extraction_result = ExtractionResult(
        sample_id="sample_1",
        raw_output='{"result":"OK"}',
        parsed_output={"result": "OK"},
        status="correct",
    )

    records = mock_evaluation.evaluate_batch([extraction_result], sample_set)
    state = sample_set.states["sample_1"]

    assert len(records) == 1
    assert records[0].status == "wrong"
    assert records[0].correct is False
    assert state.last_extraction_status == "wrong"
    assert state.error_count == 1
    assert state.error_ema == 0.3
    assert state.difficulty_score == 0.3


# ---------------------------------------------------------------------------
# SubTask 10.2: AnalysisExecutor 产出真实分析结果
# ---------------------------------------------------------------------------


def test_analysis_executor_produces_real_analysis_result():
    """测试 5：AnalysisExecutor 产出真实 AnalysisResult。

    extraction 正确（parsed_output={"result":"OK"}, ground_truth={"result":"OK"}），
    analysis 判断也正确（is_correct=true），analysis_correct 应为 True。
    """
    analysis_prompt = make_analysis_prompt()
    extraction_prompt = make_extraction_prompt()

    extraction_result = ExtractionResult(
        sample_id="sample_1",
        raw_output='{"result":"OK"}',
        parsed_output={"result": "OK"},
        status="correct",
    )
    spec = SampleSpec(
        id="sample_1",
        input={"text": "Sample text"},
        ground_truth={"result": "OK"},
    )

    # AnalysisExecutor 识别 "is_correct" 字段（实现约定的 judgement key）
    client = MockModelClient(
        default_output=json.dumps({"is_correct": True, "judgement": "match"})
    )
    executor = AnalysisExecutor(client)

    result = executor.execute(analysis_prompt, extraction_prompt, extraction_result, spec)

    assert isinstance(result, AnalysisResult)
    assert result.sample_id == "sample_1"
    # extraction 实际正确 + analysis 判断正确 → analysis_correct=True
    assert result.analysis_correct is True, (
        f"expected analysis_correct=True, got {result.analysis_correct}"
    )
    assert result.judgement, "judgement 不应为空"
    assert result.judgement.get("is_correct") is True


def test_analysis_executor_generates_patch_suggestion_for_wrong_sample():
    """测试 6：AnalysisExecutor 对错误样本生成 patch_suggestion。

    extraction 错误（parsed_output={"result":"WRONG"}, ground_truth={"result":"OK"}），
    analysis 正确识别错误（is_correct=false），analysis_correct 应为 True，
    且 patch_suggestion 不为 None。
    """
    analysis_prompt = make_analysis_prompt()
    extraction_prompt = make_extraction_prompt()

    extraction_result = ExtractionResult(
        sample_id="sample_1",
        raw_output='{"result":"WRONG"}',
        parsed_output={"result": "WRONG"},
        status="wrong",
    )
    spec = SampleSpec(
        id="sample_1",
        input={"text": "Sample text"},
        ground_truth={"result": "OK"},
    )

    client = MockModelClient(
        default_output=json.dumps(
            {
                "is_correct": False,
                "error_reason": "wrong answer",
                "patch_suggestion": {
                    "target_section": "section_1",
                    "operation": "replace",
                    "content": "clarify result extraction",
                },
            }
        )
    )
    executor = AnalysisExecutor(client)

    result = executor.execute(analysis_prompt, extraction_prompt, extraction_result, spec)

    # extraction 错误 + analysis 正确识别错误 → analysis_correct=True
    assert result.analysis_correct is True, (
        f"expected analysis_correct=True (analysis correctly identified error), "
        f"got {result.analysis_correct}"
    )
    assert result.patch_suggestion is not None, "错误样本应生成 patch_suggestion"
    assert isinstance(result.patch_suggestion, dict)
    assert result.patch_suggestion.get("content") == "clarify result extraction"
    assert result.error_reason == "wrong answer"


# ---------------------------------------------------------------------------
# SubTask 10.3: 验证无 mock status="correct" 硬编码
# ---------------------------------------------------------------------------


def test_real_executor_does_not_hardcode_correct_status():
    """测试 7：验证真实 executor 不产生硬编码 status="correct"。

    使用 MockModelClient 返回非 JSON，ExtractionExecutor 应产出 status="invalid"，
    证明 status 来自真实解析，不是硬编码。
    """
    prompt = make_extraction_prompt()
    sample_set, batch = make_sample_set(ground_truth={"result": "OK"})

    client = MockModelClient(default_output="invalid output")
    executor = ExtractionExecutor(client)

    results = executor.execute(prompt, batch, sample_set)
    assert len(results) == 1
    er = results[0]
    assert er.status == "invalid", (
        f"真实 executor 对非 JSON 输出应返回 invalid，而非硬编码 correct；"
        f"实际 status={er.status}"
    )
    assert er.parsed_output is None
    assert er.raw_output == "invalid output"


def test_factory_returns_real_executors_when_model_client_available():
    """测试 8：验证 factory 在有 model_client 时返回真实 executor。

    配置 models={"extraction": {"provider": "mock"}}，build_model_client 会
    返回 MockModelClient（provider=mock），从而触发真实 executor 分支。
    """
    config = {"models": {"extraction": {"provider": "mock"}}}
    executors = create_executors(config)

    # model_client 应非 None（MockModelClient）
    assert executors["model_client"] is not None, (
        "配置 provider=mock 时应构建出 MockModelClient"
    )

    # 4 个核心 executor 应为真实实现
    assert isinstance(executors["extraction"], ExtractionExecutor), (
        f"expected ExtractionExecutor, got {type(executors['extraction']).__name__}"
    )
    assert isinstance(executors["evaluation"], EvaluationExecutor), (
        f"expected EvaluationExecutor, got {type(executors['evaluation']).__name__}"
    )
    assert isinstance(executors["analysis"], AnalysisExecutor), (
        f"expected AnalysisExecutor, got {type(executors['analysis']).__name__}"
    )
    assert isinstance(executors["fewshot"], FewshotExecutor), (
        f"expected FewshotExecutor, got {type(executors['fewshot']).__name__}"
    )

    # 真实 executor 不应是 Mock 类型
    assert not isinstance(executors["extraction"], _MockExtractionExecutor)
    assert not isinstance(executors["evaluation"], _MockEvaluationExecutor)
    assert not isinstance(executors["analysis"], _MockAnalysisExecutor)
    assert not isinstance(executors["fewshot"], _MockFewshotExecutor)


def test_factory_returns_mock_executors_when_no_model_client():
    """测试 9：验证 factory 在无 model_client 时返回 Mock executor。

    配置 models={} （空），_build_model_client 返回 None，
    factory 应回退到 Mock executor。
    """
    config: dict[str, Any] = {"models": {}}
    executors = create_executors(config)

    # model_client 应为 None
    assert executors["model_client"] is None, (
        "空 models 配置时 model_client 应为 None"
    )

    # extraction 应为 _MockExtractionExecutor
    assert isinstance(executors["extraction"], _MockExtractionExecutor), (
        f"expected _MockExtractionExecutor, got {type(executors['extraction']).__name__}"
    )
    # 其他 executor 也应为 Mock
    assert isinstance(executors["evaluation"], _MockEvaluationExecutor)
    assert isinstance(executors["analysis"], _MockAnalysisExecutor)
    assert isinstance(executors["fewshot"], _MockFewshotExecutor)

    # 验证 Mock executor 确实硬编码 status="correct"（与真实 executor 形成对比）
    prompt = make_extraction_prompt()
    sample_set, batch = make_sample_set(ground_truth={"result": "OK"})
    mock_results = executors["extraction"].execute(prompt, batch, sample_set)
    assert len(mock_results) == 1
    assert mock_results[0].status == "correct"  # Mock 硬编码
    assert mock_results[0].parsed_output == {"mock": "data"}  # Mock 硬编码


def test_factory_returns_mock_executors_when_models_missing():
    """补充测试：config 完全没有 models 键时也应回退到 Mock executor。"""
    config: dict[str, Any] = {}
    executors = create_executors(config)
    assert executors["model_client"] is None
    assert isinstance(executors["extraction"], _MockExtractionExecutor)
    assert isinstance(executors["evaluation"], _MockEvaluationExecutor)
    assert isinstance(executors["analysis"], _MockAnalysisExecutor)
    assert isinstance(executors["fewshot"], _MockFewshotExecutor)
