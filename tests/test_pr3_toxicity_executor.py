"""PR3 单元测试：ToxicityTestExecutor。

覆盖以下场景：
1. 空 toxic set 跳过：所有非无效 patch 进入 safe_patches，报告含 skipped_reason="NO_TOXIC_SAMPLES"。
2. safe patch 接受：未 break 任何 toxic 样本的 patch 标记为 candidate_safe 并进入 safe_patches。
3. toxic patch 拒绝：break 了 toxic 样本的 patch 标记为 rejected（rejection_reason="TOXIC"）并进入 toxic_patches。
4. early stop 生效：early_stop=True 且首个 toxic 样本即 break 时，不测试剩余样本。
5. patch 排序：按难度 DESC、来源样本数量 DESC、patch_id ASC 排序。
6. patch_test_records 生成：每个 patch 对应一条记录，字段正确。
7. ineffective patch 剔除：source_sample_ids 全部属于 unchanged_wrong 的 patch 被标记 INEFFECTIVE。
"""

from __future__ import annotations

from mmap_optimizer.executors.patch_apply_executor import PatchApplyExecutor
from mmap_optimizer.executors.toxicity_executor import ToxicityTestExecutor
from mmap_optimizer.stages.extraction_prompt_optimization import (
    AnalysisResult,
    EvalRecord,
    ExtractionResult,
)
from mmap_optimizer.patch.types import (
    AnalysisPatch,
    ExtractionPatch,
    PatchTestRecord,
    ToxicityReport,
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
# Mock executors
# ---------------------------------------------------------------------------


class MockExtractionExecutor:
    """Mock extraction executor，按 sample_id 返回指定 status。"""

    def __init__(self, status_map: dict[str, str] | None = None, default_status: str = "correct") -> None:
        self.status_map = status_map or {}
        self.default_status = default_status
        self.call_log: list[str] = []  # 记录被测试的 sample_id 顺序

    def execute(self, prompt, batch, sample_set, fewshot_examples=None):
        results = []
        for sample_id in batch.sample_ids:
            self.call_log.append(sample_id)
            status = self.status_map.get(sample_id, self.default_status)
            results.append(
                ExtractionResult(
                    sample_id=sample_id,
                    raw_output=f'{{"result":"{status}"}}',
                    parsed_output={"result": status},
                    status=status,
                )
            )
        return results


class MockEvaluationExecutor:
    """Mock evaluation executor，根据 extraction_result.status 判断 correct。"""

    def evaluate(self, extraction_result, ground_truth, sample_state=None):
        correct = extraction_result.status == "correct"
        return EvalRecord(
            sample_id=extraction_result.sample_id,
            extraction_result_id=extraction_result.sample_id,
            status=extraction_result.status,
            correct=correct,
        )

    def evaluate_batch(self, extraction_results, sample_set):
        return [self.evaluate(r, {}) for r in extraction_results]


class MockAnalysisExecutor:
    """Mock analysis executor，按 sample_id 返回指定 analysis_correct。"""

    def __init__(self, correct_map: dict[str, bool] | None = None, default_correct: bool = True) -> None:
        self.correct_map = correct_map or {}
        self.default_correct = default_correct
        self.call_log: list[str] = []

    def execute(self, analysis_prompt, extraction_prompt, extraction_result, sample_spec):
        self.call_log.append(extraction_result.sample_id)
        analysis_correct = self.correct_map.get(
            extraction_result.sample_id, self.default_correct
        )
        return AnalysisResult(
            sample_id=extraction_result.sample_id,
            judgement={"correct": analysis_correct},
            analysis_correct=analysis_correct,
        )

    def execute_batch(self, analysis_prompt, extraction_prompt, extraction_results, sample_set):
        return [
            self.execute(analysis_prompt, extraction_prompt, r, None)
            for r in extraction_results
        ]

    def reflect(self, analysis_prompt, extraction_result, analysis_result, sample_spec):
        return None


# ---------------------------------------------------------------------------
# Helper constructors
# ---------------------------------------------------------------------------


def make_extraction_prompt() -> StructuredPrompt:
    """构造含 mutable section_1 的 extraction StructuredPrompt。"""
    section = PromptSection(
        id="section_1",
        title="Task",
        level=1,
        content="Extract the answer",
        mutable=True,
    )
    return StructuredPrompt(
        id="p1",
        prompt_type="extraction",
        sections=[section],
        raw_markdown="# Task\nExtract the answer",
        version=1,
    )


def make_analysis_prompt() -> StructuredPrompt:
    """构造含 mutable section_1 的 analysis StructuredPrompt。"""
    section = PromptSection(
        id="section_1",
        title="Analysis Task",
        level=1,
        content="Analyze the extraction",
        mutable=True,
    )
    return StructuredPrompt(
        id="pa1",
        prompt_type="analysis",
        sections=[section],
        raw_markdown="# Analysis Task\nAnalyze the extraction",
        version=1,
    )


def make_patch(patch_id: str, source_sample_ids: list[str]) -> ExtractionPatch:
    """构造一个 ExtractionPatch。"""
    return ExtractionPatch(
        id=patch_id,
        target_section_id="section_1",
        operation_type="replace_section",
        content=f"content for {patch_id}",
        rationale=f"rationale for {patch_id}",
        source_sample_ids=list(source_sample_ids),
        status="draft",
    )


def make_analysis_patch(patch_id: str, source_sample_ids: list[str]) -> AnalysisPatch:
    """构造一个 AnalysisPatch。"""
    return AnalysisPatch(
        id=patch_id,
        target_section_id="section_1",
        operation_type="replace_section",
        content=f"content for {patch_id}",
        rationale=f"rationale for {patch_id}",
        source_sample_ids=list(source_sample_ids),
        status="draft",
    )


def make_sample_set(
    sample_ids: list[str],
    difficulty_scores: dict[str, float] | None = None,
) -> SampleSet:
    """构造含多个样本的 SampleSet。"""
    specs: dict[str, SampleSpec] = {}
    states: dict[str, SampleState] = {}
    difficulty_scores = difficulty_scores or {}
    for sid in sample_ids:
        specs[sid] = SampleSpec(id=sid, input={}, ground_truth={"result": "A"})
        state = SampleState(sample_id=sid)
        state.difficulty_score = difficulty_scores.get(sid, 0.0)
        states[sid] = state
    return SampleSet(specs=specs, states=states)


# ---------------------------------------------------------------------------
# Test 1: 空 toxic set 跳过
# ---------------------------------------------------------------------------


def test_empty_toxic_set_skipped():
    """空 toxic_sample_ids 时所有非无效 patch 进入 safe_patches，报告含 skipped_reason。"""
    prompt = make_extraction_prompt()
    sample_set = make_sample_set(["s1", "s2"])
    patches = [make_patch("p1", ["s1"]), make_patch("p2", ["s2"])]

    executor = ToxicityTestExecutor(patch_apply_executor=PatchApplyExecutor())
    safe_patches, toxic_patches, report = executor.test(
        base_prompt=prompt,
        candidate_patches=patches,
        toxic_sample_ids=[],
        sample_set=sample_set,
        mode="extraction",
    )

    # 所有非无效 patch 进入 safe_patches
    assert len(safe_patches) == 2
    assert len(toxic_patches) == 0
    assert {p.id for p in safe_patches} == {"p1", "p2"}

    # patch 状态为 candidate_safe
    for p in safe_patches:
        assert p.status == "candidate_safe"

    # 报告含 skipped_reason
    assert report.metadata.get("skipped_reason") == "NO_TOXIC_SAMPLES"
    assert report.safe_patch_count == 2
    assert report.toxic_patch_count == 0
    assert report.tested_patch_count == 2

    # patch_test_records 中每条记录 status="skipped"
    assert len(report.patch_test_records) == 2
    for record in report.patch_test_records:
        assert record["status"] == "skipped"
        assert record["stop_reason"] == "NO_TOXIC_SAMPLES"


# ---------------------------------------------------------------------------
# Test 2: safe patch accepted
# ---------------------------------------------------------------------------


def test_safe_patch_accepted():
    """未 break 任何 toxic 样本的 patch 标记为 candidate_safe 并进入 safe_patches。"""
    prompt = make_extraction_prompt()
    sample_set = make_sample_set(["s1", "s2"])

    patches = [make_patch("p1", ["s1"])]

    # Mock extraction 返回 correct（不 break）
    extraction_executor = MockExtractionExecutor(default_status="correct")
    evaluation_executor = MockEvaluationExecutor()

    executor = ToxicityTestExecutor(patch_apply_executor=PatchApplyExecutor())
    safe_patches, toxic_patches, report = executor.test(
        base_prompt=prompt,
        candidate_patches=patches,
        toxic_sample_ids=["s1", "s2"],
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
    )

    assert len(safe_patches) == 1
    assert len(toxic_patches) == 0
    assert safe_patches[0].id == "p1"
    assert safe_patches[0].status == "candidate_safe"
    assert safe_patches[0].rejection_reason is None

    assert report.safe_patch_count == 1
    assert report.toxic_patch_count == 0
    assert "p1" in report.safe_patches
    assert "p1" in report.safe_patch_ids


# ---------------------------------------------------------------------------
# Test 3: toxic patch rejected
# ---------------------------------------------------------------------------


def test_toxic_patch_rejected():
    """break 了 toxic 样本的 patch 标记为 rejected（TOXIC）并进入 toxic_patches。"""
    prompt = make_extraction_prompt()
    sample_set = make_sample_set(["s1", "s2"])

    patches = [make_patch("p1", ["s1"])]

    # Mock extraction 返回 wrong（break）
    extraction_executor = MockExtractionExecutor(default_status="wrong")
    evaluation_executor = MockEvaluationExecutor()

    executor = ToxicityTestExecutor(patch_apply_executor=PatchApplyExecutor())
    safe_patches, toxic_patches, report = executor.test(
        base_prompt=prompt,
        candidate_patches=patches,
        toxic_sample_ids=["s1", "s2"],
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        early_stop=False,  # 关闭 early stop 以测试所有样本
    )

    assert len(toxic_patches) == 1
    assert len(safe_patches) == 0
    assert toxic_patches[0].id == "p1"
    assert toxic_patches[0].status == "rejected"
    assert toxic_patches[0].rejection_reason == "TOXIC"

    assert report.toxic_patch_count == 1
    assert report.safe_patch_count == 0
    assert "p1" in report.toxic_patches
    assert "p1" in report.toxic_patch_ids


# ---------------------------------------------------------------------------
# Test 4: early stop 生效
# ---------------------------------------------------------------------------


def test_early_stop_effective():
    """early_stop=True 且首个 toxic 样本即 break 时，不测试剩余样本。"""
    prompt = make_extraction_prompt()
    sample_set = make_sample_set(["s1", "s2", "s3"])

    patches = [make_patch("p1", ["s1"])]

    # Mock extraction 默认返回 wrong（首个样本即 break）
    extraction_executor = MockExtractionExecutor(default_status="wrong")
    evaluation_executor = MockEvaluationExecutor()

    executor = ToxicityTestExecutor(patch_apply_executor=PatchApplyExecutor())
    safe_patches, toxic_patches, report = executor.test(
        base_prompt=prompt,
        candidate_patches=patches,
        toxic_sample_ids=["s1", "s2", "s3"],
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        early_stop=True,
    )

    # 应当是 toxic
    assert len(toxic_patches) == 1
    assert toxic_patches[0].id == "p1"

    # 只测试了首个样本（early stop 生效）
    assert len(extraction_executor.call_log) == 1
    assert extraction_executor.call_log[0] == "s1"

    # patch_test_records 中 tested_sample_ids 长度为 1，stop_reason 为 EARLY_STOP_BROKEN
    assert len(report.patch_test_records) == 1
    record = report.patch_test_records[0]
    assert len(record["tested_sample_ids"]) == 1
    assert record["tested_sample_ids"][0] == "s1"
    assert record["stop_reason"] == "EARLY_STOP_BROKEN"
    assert record["status"] == "toxic"


def test_early_stop_disabled_tests_all_samples():
    """early_stop=False 时即使 break 也测试所有样本。"""
    prompt = make_extraction_prompt()
    sample_set = make_sample_set(["s1", "s2", "s3"])

    patches = [make_patch("p1", ["s1"])]

    extraction_executor = MockExtractionExecutor(default_status="wrong")
    evaluation_executor = MockEvaluationExecutor()

    executor = ToxicityTestExecutor(patch_apply_executor=PatchApplyExecutor())
    safe_patches, toxic_patches, report = executor.test(
        base_prompt=prompt,
        candidate_patches=patches,
        toxic_sample_ids=["s1", "s2", "s3"],
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        early_stop=False,
    )

    # 仍然是 toxic
    assert len(toxic_patches) == 1

    # 但所有样本都被测试
    assert len(extraction_executor.call_log) == 3

    # patch_test_records 中 tested_sample_ids 长度为 3，无 stop_reason
    record = report.patch_test_records[0]
    assert len(record["tested_sample_ids"]) == 3
    assert record["stop_reason"] is None


# ---------------------------------------------------------------------------
# Test 5: patch 排序
# ---------------------------------------------------------------------------


def test_patch_sorting():
    """patch 按难度 DESC、来源样本数量 DESC、patch_id ASC 排序。"""
    prompt = make_extraction_prompt()
    sample_set = make_sample_set(
        ["s1", "s2", "s3", "s4"],
        difficulty_scores={"s1": 0.1, "s2": 0.5, "s3": 0.9, "s4": 0.5},
    )

    # 构造多个 patch，验证排序
    # p_low: 来源 s1，难度 0.1
    # p_high: 来源 s3，难度 0.9
    # p_mid_multi: 来源 s2,s4，难度 max(0.5,0.5)=0.5，但来源数 2
    # p_mid_single: 来源 s2，难度 0.5，来源数 1
    # p_tie_a: 来源 s4，难度 0.5，来源数 1，id="p_tie_a"
    # p_tie_b: 来源 s4，难度 0.5，来源数 1，id="p_tie_b"
    patches = [
        make_patch("p_low", ["s1"]),
        make_patch("p_high", ["s3"]),
        make_patch("p_mid_multi", ["s2", "s4"]),
        make_patch("p_mid_single", ["s2"]),
        make_patch("p_tie_b", ["s4"]),
        make_patch("p_tie_a", ["s4"]),
    ]

    extraction_executor = MockExtractionExecutor(default_status="correct")
    evaluation_executor = MockEvaluationExecutor()

    executor = ToxicityTestExecutor(patch_apply_executor=PatchApplyExecutor())
    safe_patches, toxic_patches, report = executor.test(
        base_prompt=prompt,
        candidate_patches=patches,
        toxic_sample_ids=["s1"],
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        early_stop=True,
    )

    # 期望顺序：
    # 1. p_high (难度 0.9)
    # 2. p_mid_multi (难度 0.5, 来源数 2)
    # 3. p_mid_single (难度 0.5, 来源数 1, id="p_mid_single")
    # 4. p_tie_a (难度 0.5, 来源数 1, id="p_tie_a")
    # 5. p_tie_b (难度 0.5, 来源数 1, id="p_tie_b")
    # 6. p_low (难度 0.1)
    actual_order = [p.id for p in safe_patches]
    expected_order = [
        "p_high",
        "p_mid_multi",
        "p_mid_single",
        "p_tie_a",
        "p_tie_b",
        "p_low",
    ]
    assert actual_order == expected_order, (
        f"patch 排序不正确：actual={actual_order}, expected={expected_order}"
    )


# ---------------------------------------------------------------------------
# Test 6: patch_test_records 生成
# ---------------------------------------------------------------------------


def test_patch_test_records_generation():
    """每个 patch 对应一条 PatchTestRecord，字段正确。"""
    prompt = make_extraction_prompt()
    sample_set = make_sample_set(["s1", "s2"])

    patches = [
        make_patch("p_safe", ["s1"]),
        make_patch("p_toxic", ["s2"]),
    ]

    # p_safe 不 break，p_toxic break
    # 通过 status_map 控制：对 p_safe 应用后所有样本 correct，
    # 对 p_toxic 应用后样本 wrong
    # 由于 mock 是按 sample_id 返回，无法区分 patch；
    # 改用：第一个 patch 测试时 correct，第二个 patch 测试时 wrong
    # 这里用一个可切换的 mock
    class SwitchableExtractionExecutor:
        def __init__(self):
            self.status = "correct"
            self.call_log: list[str] = []

        def execute(self, prompt, batch, sample_set, fewshot_examples=None):
            results = []
            for sample_id in batch.sample_ids:
                self.call_log.append(sample_id)
                results.append(
                    ExtractionResult(
                        sample_id=sample_id,
                        raw_output=f'{{"result":"{self.status}"}}',
                        parsed_output={"result": self.status},
                        status=self.status,
                    )
                )
            return results

    extraction_executor = SwitchableExtractionExecutor()
    evaluation_executor = MockEvaluationExecutor()

    # 由于无法在 test() 内部切换 mock 状态，分两次测试：
    # 第一次：两个 patch 都 safe
    extraction_executor.status = "correct"
    executor = ToxicityTestExecutor(patch_apply_executor=PatchApplyExecutor())
    safe_patches, toxic_patches, report = executor.test(
        base_prompt=prompt,
        candidate_patches=[make_patch("p_safe", ["s1"]), make_patch("p_toxic", ["s2"])],
        toxic_sample_ids=["s1", "s2"],
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        early_stop=False,
    )

    # 两条记录，都是 safe
    assert len(report.patch_test_records) == 2
    for record in report.patch_test_records:
        assert record["status"] == "safe"
        assert len(record["tested_sample_ids"]) == 2
        assert set(record["tested_sample_ids"]) == {"s1", "s2"}
        assert record["broken_sample_ids"] == []
        assert record["stop_reason"] is None

    # 第二次：两个 patch 都 toxic（mock 返回 wrong）
    extraction_executor.status = "wrong"
    executor = ToxicityTestExecutor(patch_apply_executor=PatchApplyExecutor())
    safe_patches, toxic_patches, report = executor.test(
        base_prompt=prompt,
        candidate_patches=[make_patch("p_safe", ["s1"]), make_patch("p_toxic", ["s2"])],
        toxic_sample_ids=["s1", "s2"],
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        early_stop=False,
    )

    # 两条记录，都是 toxic
    assert len(report.patch_test_records) == 2
    for record in report.patch_test_records:
        assert record["status"] == "toxic"
        assert len(record["tested_sample_ids"]) == 2
        assert len(record["broken_sample_ids"]) == 2
        assert set(record["broken_sample_ids"]) == {"s1", "s2"}
        assert record["stop_reason"] is None  # early_stop=False


def test_patch_test_records_round_trip():
    """PatchTestRecord 的 to_dict / from_dict 可往返。"""
    record = PatchTestRecord(
        patch_id="p1",
        status="toxic",
        tested_sample_ids=["s1", "s2"],
        broken_sample_ids=["s1"],
        fixed_sample_ids=[],
        stop_reason="EARLY_STOP_BROKEN",
    )
    d = record.to_dict()
    assert d["patch_id"] == "p1"
    assert d["status"] == "toxic"
    assert d["tested_sample_ids"] == ["s1", "s2"]
    assert d["broken_sample_ids"] == ["s1"]
    assert d["stop_reason"] == "EARLY_STOP_BROKEN"

    restored = PatchTestRecord.from_dict(d)
    assert restored.patch_id == "p1"
    assert restored.status == "toxic"
    assert restored.tested_sample_ids == ["s1", "s2"]
    assert restored.broken_sample_ids == ["s1"]
    assert restored.stop_reason == "EARLY_STOP_BROKEN"


def test_toxicity_report_round_trip():
    """ToxicityReport 的 to_dict / from_dict 可往返，且包含新字段。"""
    report = ToxicityReport(
        id="r1",
        tested_patch_count=2,
        toxic_patch_count=1,
        safe_patch_count=1,
        toxic_patches=["p2"],
        safe_patches=["p1"],
        toxic_sample_ids=["s1"],
        metadata={"key": "value"},
        mode="analysis",
        safe_patch_ids=["p1"],
        toxic_patch_ids=["p2"],
        patch_test_records=[{"patch_id": "p1", "status": "safe"}],
        early_stop_enabled=False,
    )
    d = report.to_dict()
    assert d["mode"] == "analysis"
    assert d["safe_patch_ids"] == ["p1"]
    assert d["toxic_patch_ids"] == ["p2"]
    assert d["early_stop_enabled"] is False
    assert len(d["patch_test_records"]) == 1

    restored = ToxicityReport.from_dict(d)
    assert restored.mode == "analysis"
    assert restored.safe_patch_ids == ["p1"]
    assert restored.toxic_patch_ids == ["p2"]
    assert restored.early_stop_enabled is False
    assert len(restored.patch_test_records) == 1


# ---------------------------------------------------------------------------
# Test 7: ineffective patch 剔除
# ---------------------------------------------------------------------------


def test_ineffective_patch_filtered():
    """source_sample_ids 全部属于 unchanged_wrong 的 patch 被标记 INEFFECTIVE。"""
    prompt = make_extraction_prompt()
    sample_set = make_sample_set(["s1", "s2", "s3"])

    # p_ineffective: 来源 s1,s2，全部属于 unchanged_wrong
    # p_effective: 来源 s3，不属于 unchanged_wrong
    # p_partial: 来源 s1,s3，部分属于 unchanged_wrong（不全部），仍有效
    patches = [
        make_patch("p_ineffective", ["s1", "s2"]),
        make_patch("p_effective", ["s3"]),
        make_patch("p_partial", ["s1", "s3"]),
    ]

    extraction_executor = MockExtractionExecutor(default_status="correct")
    evaluation_executor = MockEvaluationExecutor()

    executor = ToxicityTestExecutor(patch_apply_executor=PatchApplyExecutor())
    safe_patches, toxic_patches, report = executor.test(
        base_prompt=prompt,
        candidate_patches=patches,
        toxic_sample_ids=["s3"],
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        unchanged_wrong_sample_ids=["s1", "s2"],
    )

    # p_ineffective 不进入 safe_patches
    safe_ids = {p.id for p in safe_patches}
    assert "p_ineffective" not in safe_ids
    assert "p_effective" in safe_ids
    assert "p_partial" in safe_ids

    # p_ineffective 状态为 rejected，rejection_reason 为 INEFFECTIVE
    # 在原 candidate_patches 中查找
    p_ineffective = next(p for p in patches if p.id == "p_ineffective")
    assert p_ineffective.status == "rejected"
    assert p_ineffective.rejection_reason == "INEFFECTIVE"

    # 报告 metadata 中记录了 ineffective 信息
    assert report.metadata.get("ineffective_patch_count") == 1
    assert "p_ineffective" in report.metadata.get("ineffective_patch_ids", [])

    # tested_patch_count 不包含 ineffective patch
    assert report.tested_patch_count == 2


# ---------------------------------------------------------------------------
# Test 8: analysis 模式
# ---------------------------------------------------------------------------


def test_analysis_mode_safe_patch():
    """analysis 模式下未 break 的 patch 进入 safe_patches。"""
    analysis_prompt = make_analysis_prompt()
    extraction_prompt = make_extraction_prompt()
    sample_set = make_sample_set(["s1", "s2"])

    patches = [make_analysis_patch("pa1", ["s1"])]

    # 构造 extraction_results（analysis 模式必需）
    extraction_results = [
        ExtractionResult(
            sample_id="s1",
            raw_output='{"result":"A"}',
            parsed_output={"result": "A"},
            status="correct",
        ),
        ExtractionResult(
            sample_id="s2",
            raw_output='{"result":"B"}',
            parsed_output={"result": "B"},
            status="correct",
        ),
    ]

    # Mock analysis 返回 analysis_correct=True（不 break）
    analysis_executor = MockAnalysisExecutor(default_correct=True)

    executor = ToxicityTestExecutor(patch_apply_executor=PatchApplyExecutor())
    safe_patches, toxic_patches, report = executor.test(
        base_prompt=analysis_prompt,
        candidate_patches=patches,
        toxic_sample_ids=["s1", "s2"],
        sample_set=sample_set,
        mode="analysis",
        analysis_executor=analysis_executor,
        extraction_results=extraction_results,
        extraction_prompt=extraction_prompt,
    )

    assert len(safe_patches) == 1
    assert len(toxic_patches) == 0
    assert safe_patches[0].status == "candidate_safe"
    assert report.mode == "analysis"


def test_analysis_mode_toxic_patch():
    """analysis 模式下 break 的 patch 进入 toxic_patches。"""
    analysis_prompt = make_analysis_prompt()
    extraction_prompt = make_extraction_prompt()
    sample_set = make_sample_set(["s1", "s2"])

    patches = [make_analysis_patch("pa1", ["s1"])]

    extraction_results = [
        ExtractionResult(
            sample_id="s1",
            raw_output='{"result":"A"}',
            parsed_output={"result": "A"},
            status="correct",
        ),
        ExtractionResult(
            sample_id="s2",
            raw_output='{"result":"B"}',
            parsed_output={"result": "B"},
            status="correct",
        ),
    ]

    # Mock analysis 返回 analysis_correct=False（break）
    analysis_executor = MockAnalysisExecutor(default_correct=False)

    executor = ToxicityTestExecutor(patch_apply_executor=PatchApplyExecutor())
    safe_patches, toxic_patches, report = executor.test(
        base_prompt=analysis_prompt,
        candidate_patches=patches,
        toxic_sample_ids=["s1", "s2"],
        sample_set=sample_set,
        mode="analysis",
        analysis_executor=analysis_executor,
        extraction_results=extraction_results,
        extraction_prompt=extraction_prompt,
        early_stop=False,
    )

    assert len(toxic_patches) == 1
    assert len(safe_patches) == 0
    assert toxic_patches[0].status == "rejected"
    assert toxic_patches[0].rejection_reason == "TOXIC"
