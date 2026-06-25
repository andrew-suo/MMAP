"""PR4 单元测试：CompressionExecutor。

覆盖以下场景：
1. 未超限时不压缩：triggered=False, rejected_reason="NOT_NEEDED"。
2. 超行数限制触发压缩：triggered=True。
3. 超字符限制触发压缩：triggered=True。
4. 压缩后准确率未下降时接受：accepted=True。
5. 压缩后准确率下降时拒绝：accepted=False，返回原 prompt。
6. immutable section 不被修改。
7. 压缩后 prompt 可正常渲染 to_markdown()。
8. CompressionReport 字段完整填充。
"""

from __future__ import annotations

from mmap_optimizer.executors.compression_executor import CompressionExecutor
from mmap_optimizer.stages.extraction_prompt_optimization import (
    AnalysisResult,
    EvalRecord,
    ExtractionResult,
)
from mmap_optimizer.patch.types import CompressionReport
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


class PromptAwareExtractionExecutor:
    """Mock extraction executor，根据 prompt 是否为压缩版返回不同 status。

    通过 prompt.id 是否以 ``_compressed`` 结尾来区分压缩前后。
    """

    def __init__(self, compressed_status: str = "correct", default_status: str = "correct") -> None:
        self.compressed_status = compressed_status
        self.default_status = default_status
        self.call_log: list[str] = []

    def execute(self, prompt, batch, sample_set, fewshot_examples=None):
        results = []
        status = (
            self.compressed_status
            if prompt.id.endswith("_compressed")
            else self.default_status
        )
        for sample_id in batch.sample_ids:
            self.call_log.append(sample_id)
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


class PromptAwareAnalysisExecutor:
    """Mock analysis executor，根据 prompt 是否为压缩版返回不同 analysis_correct。"""

    def __init__(self, compressed_correct: bool = True, default_correct: bool = True) -> None:
        self.compressed_correct = compressed_correct
        self.default_correct = default_correct

    def execute(self, analysis_prompt, extraction_prompt, extraction_result, sample_spec):
        analysis_correct = (
            self.compressed_correct
            if analysis_prompt.id.endswith("_compressed")
            else self.default_correct
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


def make_large_prompt() -> StructuredPrompt:
    """构造含重复行和连续空行的 mutable extraction prompt（超行数和字符限制）。"""
    content = (
        "Important rule\n"
        "Important rule\n"
        "\n\n\n"
        "Another rule\n"
        "Another rule\n"
        "\n\n"
        "Final rule\n"
        "Final rule"
    )
    section = PromptSection(
        id="section_1",
        title="Task",
        level=1,
        content=content,
        mutable=True,
    )
    return StructuredPrompt(
        id="p1",
        prompt_type="extraction",
        sections=[section],
        raw_markdown="",
        version=1,
    )


def make_long_char_prompt() -> StructuredPrompt:
    """构造超字符限制但未超行数限制的 prompt（含重复长行）。"""
    long_line = "x" * 100
    content = long_line + "\n" + long_line  # 重复长行
    section = PromptSection(
        id="section_1",
        title="Task",
        level=1,
        content=content,
        mutable=True,
    )
    return StructuredPrompt(
        id="p1",
        prompt_type="extraction",
        sections=[section],
        raw_markdown="",
        version=1,
    )


def make_prompt_with_immutable() -> StructuredPrompt:
    """构造含 immutable section 和 mutable section 的 prompt。"""
    immutable_section = PromptSection(
        id="section_immutable",
        title="Fixed Rules",
        level=1,
        content="Do not change this\nDo not change this\n\n\nKeep as is",
        mutable=False,
    )
    mutable_section = PromptSection(
        id="section_mutable",
        title="Mutable Task",
        level=1,
        content="Compress me\nCompress me\n\n\nAlso compress me\nAlso compress me",
        mutable=True,
    )
    return StructuredPrompt(
        id="p1",
        prompt_type="extraction",
        sections=[immutable_section, mutable_section],
        raw_markdown="",
        version=1,
    )


def make_sample_set(sample_ids: list[str]) -> SampleSet:
    """构造含多个样本的 SampleSet。"""
    specs: dict[str, SampleSpec] = {}
    states: dict[str, SampleState] = {}
    for sid in sample_ids:
        specs[sid] = SampleSpec(id=sid, input={}, ground_truth={"result": "A"})
        states[sid] = SampleState(sample_id=sid)
    return SampleSet(specs=specs, states=states)


def make_batch(sample_ids: list[str]) -> SampleBatch:
    """构造 SampleBatch。"""
    return SampleBatch(
        id="batch_1",
        phase="prompt_optimization",
        iteration=1,
        sample_ids=list(sample_ids),
        sampler_name="mock",
    )


def make_eval_records(sample_ids: list[str], status: str = "correct") -> list[EvalRecord]:
    """构造 EvalRecord 列表。"""
    return [
        EvalRecord(
            sample_id=sid,
            extraction_result_id=sid,
            status=status,
            correct=(status == "correct"),
        )
        for sid in sample_ids
    ]


# ---------------------------------------------------------------------------
# Test 1: 未超限时不压缩
# ---------------------------------------------------------------------------


def test_not_over_limit_no_compression():
    """prompt 未超行数和字符限制时，triggered=False, rejected_reason='NOT_NEEDED'。"""
    prompt = make_large_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    executor = CompressionExecutor()
    # 设置足够大的限制
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=1000,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=PromptAwareExtractionExecutor(),
        evaluation_executor=MockEvaluationExecutor(),
    )

    assert report.triggered is False
    assert report.rejected_reason == "NOT_NEEDED"
    assert report.accepted is False
    # 返回原 prompt
    assert result_prompt.id == prompt.id
    # before == after
    assert report.line_count_before == report.line_count_after
    assert report.char_count_before == report.char_count_after


# ---------------------------------------------------------------------------
# Test 2: 超行数限制触发压缩
# ---------------------------------------------------------------------------


def test_over_line_limit_triggers_compression():
    """prompt 超行数限制时，triggered=True。"""
    prompt = make_large_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    executor = CompressionExecutor()
    # line_limit 设小，char_limit 设大，只触发行数限制
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=PromptAwareExtractionExecutor(compressed_status="correct"),
        evaluation_executor=MockEvaluationExecutor(),
        pre_compression_eval_records=make_eval_records(sample_ids, "correct"),
    )

    assert report.triggered is True
    # 压缩后行数应减少
    assert report.line_count_after < report.line_count_before


# ---------------------------------------------------------------------------
# Test 3: 超字符限制触发压缩
# ---------------------------------------------------------------------------


def test_over_char_limit_triggers_compression():
    """prompt 超字符限制时，triggered=True。"""
    prompt = make_long_char_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    # 验证未超行数限制
    md = prompt.to_markdown()
    assert len(md.splitlines()) <= 10

    executor = CompressionExecutor()
    # line_limit 设大，char_limit 设小，只触发字符限制
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=1000,
        char_limit=150,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=PromptAwareExtractionExecutor(compressed_status="correct"),
        evaluation_executor=MockEvaluationExecutor(),
        pre_compression_eval_records=make_eval_records(sample_ids, "correct"),
    )

    assert report.triggered is True
    # 压缩后字符数应减少
    assert report.char_count_after < report.char_count_before


# ---------------------------------------------------------------------------
# Test 4: 压缩后准确率未下降时接受
# ---------------------------------------------------------------------------


def test_compression_accepted_when_accuracy_not_drop():
    """压缩后准确率未下降时，accepted=True，返回压缩后的 prompt。"""
    prompt = make_large_prompt()
    sample_ids = ["s1", "s2", "s3"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    # 压缩前全部 correct（pre_acc = 1.0）
    pre_eval_records = make_eval_records(sample_ids, "correct")

    # 压缩后也全部 correct（post_acc = 1.0），不下降
    extraction_executor = PromptAwareExtractionExecutor(compressed_status="correct")
    evaluation_executor = MockEvaluationExecutor()

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=10,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        pre_compression_eval_records=pre_eval_records,
    )

    assert report.triggered is True
    assert report.accepted is True
    assert report.rejected_reason is None
    # 返回压缩后的 prompt
    assert result_prompt.id == "p1_compressed"
    assert report.compressed_prompt_id == "p1_compressed"
    # 准确率未下降
    assert report.pre_compression_accuracy == 1.0
    assert report.post_compression_accuracy == 1.0
    # 无 broken 样本
    assert report.broken_sample_ids == []
    # 压缩后未超限（原 13 行 > 10，压缩后 7 行 <= 10）
    assert report.still_over_limit is False


# ---------------------------------------------------------------------------
# Test 5: 压缩后准确率下降时拒绝
# ---------------------------------------------------------------------------


def test_compression_rejected_when_accuracy_drops():
    """压缩后准确率下降时，accepted=False，返回原 prompt，rejected_reason='ACCURACY_DROP'。"""
    prompt = make_large_prompt()
    sample_ids = ["s1", "s2", "s3"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    # 压缩前全部 correct（pre_acc = 1.0）
    pre_eval_records = make_eval_records(sample_ids, "correct")

    # 压缩后全部 wrong（post_acc = 0.0），下降
    extraction_executor = PromptAwareExtractionExecutor(compressed_status="wrong")
    evaluation_executor = MockEvaluationExecutor()

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        pre_compression_eval_records=pre_eval_records,
    )

    assert report.triggered is True
    assert report.accepted is False
    assert report.rejected_reason == "ACCURACY_DROP"
    # 返回原 prompt
    assert result_prompt.id == prompt.id
    # 准确率下降
    assert report.pre_compression_accuracy == 1.0
    assert report.post_compression_accuracy == 0.0


# ---------------------------------------------------------------------------
# Test 6: immutable section 不被修改
# ---------------------------------------------------------------------------


def test_immutable_section_not_modified():
    """压缩后 immutable section 内容不变。"""
    prompt = make_prompt_with_immutable()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    # 记录原始 immutable section 内容
    orig_immutable = prompt.get_section_by_id("section_immutable")
    orig_immutable_content = orig_immutable.content

    extraction_executor = PromptAwareExtractionExecutor(compressed_status="correct")
    evaluation_executor = MockEvaluationExecutor()

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        pre_compression_eval_records=make_eval_records(sample_ids, "correct"),
    )

    # 压缩被接受
    assert report.accepted is True
    assert report.warnings == []

    # immutable section 内容未变
    comp_immutable = result_prompt.get_section_by_id("section_immutable")
    assert comp_immutable.content == orig_immutable_content

    # mutable section 内容应被压缩（行数减少）
    orig_mutable = prompt.get_section_by_id("section_mutable")
    comp_mutable = result_prompt.get_section_by_id("section_mutable")
    assert len(comp_mutable.content.splitlines()) < len(orig_mutable.content.splitlines())


# ---------------------------------------------------------------------------
# Test 7: 压缩后 prompt 可正常渲染
# ---------------------------------------------------------------------------


def test_compressed_prompt_can_render():
    """压缩后的 prompt 可正常调用 to_markdown() 不报错。"""
    prompt = make_large_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    extraction_executor = PromptAwareExtractionExecutor(compressed_status="correct")
    evaluation_executor = MockEvaluationExecutor()

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        pre_compression_eval_records=make_eval_records(sample_ids, "correct"),
    )

    assert report.accepted is True

    # 压缩后的 prompt 可正常渲染
    markdown = result_prompt.to_markdown()
    assert isinstance(markdown, str)
    assert len(markdown) > 0
    # raw_markdown 也应已设置
    assert result_prompt.raw_markdown == markdown
    # 渲染后行数应小于原 prompt
    orig_md = prompt.to_markdown()
    assert len(markdown.splitlines()) < len(orig_md.splitlines())


# ---------------------------------------------------------------------------
# Test 8: CompressionReport 字段完整填充
# ---------------------------------------------------------------------------


def test_compression_report_fields_complete():
    """接受的 CompressionReport 所有字段被正确填充。"""
    prompt = make_large_prompt()
    sample_ids = ["s1", "s2", "s3"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    pre_eval_records = make_eval_records(sample_ids, "correct")

    extraction_executor = PromptAwareExtractionExecutor(compressed_status="correct")
    evaluation_executor = MockEvaluationExecutor()

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=10,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        pre_compression_eval_records=pre_eval_records,
    )

    # 验证所有字段
    assert isinstance(report, CompressionReport)
    assert report.id == "compression_extraction_p1"
    assert report.prompt_type == "extraction"
    assert report.base_prompt_id == "p1"
    assert report.compressed_prompt_id == "p1_compressed"
    assert report.triggered is True
    assert report.accepted is True
    assert report.rejected_reason is None
    assert report.line_count_before > 0
    assert report.line_count_after > 0
    assert report.line_count_after < report.line_count_before
    assert report.char_count_before > 0
    assert report.char_count_after > 0
    assert report.char_count_after < report.char_count_before
    assert report.base_accuracy is None  # 未传入 base_accuracy
    assert report.pre_compression_accuracy == 1.0
    assert report.post_compression_accuracy == 1.0
    assert isinstance(report.broken_sample_ids, list)
    assert report.broken_sample_ids == []
    assert isinstance(report.fixed_sample_ids, list)
    assert report.fixed_sample_ids == []
    assert isinstance(report.warnings, list)
    assert report.warnings == []
    assert report.still_over_limit is False

    # to_dict / from_dict 往返
    d = report.to_dict()
    assert d["id"] == "compression_extraction_p1"
    assert d["triggered"] is True
    assert d["accepted"] is True
    assert d["pre_compression_accuracy"] == 1.0

    restored = CompressionReport.from_dict(d)
    assert restored.id == report.id
    assert restored.triggered is True
    assert restored.accepted is True
    assert restored.pre_compression_accuracy == 1.0
    assert restored.post_compression_accuracy == 1.0
    assert restored.compressed_prompt_id == "p1_compressed"
    assert restored.still_over_limit is False


# ---------------------------------------------------------------------------
# Test 9: analysis 模式压缩接受
# ---------------------------------------------------------------------------


def test_analysis_mode_compression_accepted():
    """analysis 模式下压缩后准确率未下降时接受。"""
    # 构造 analysis prompt
    content = (
        "Analyze step one\n"
        "Analyze step one\n"
        "\n\n"
        "Analyze step two\n"
        "Analyze step two"
    )
    section = PromptSection(
        id="section_1",
        title="Analysis Task",
        level=1,
        content=content,
        mutable=True,
    )
    analysis_prompt = StructuredPrompt(
        id="pa1",
        prompt_type="analysis",
        sections=[section],
        raw_markdown="",
        version=1,
    )

    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    # 构造 extraction_results（analysis 模式必需）
    extraction_results = [
        ExtractionResult(
            sample_id=sid,
            raw_output='{"result":"A"}',
            parsed_output={"result": "A"},
            status="correct",
        )
        for sid in sample_ids
    ]

    # 压缩前 analysis 全部 correct
    pre_analysis_results = [
        AnalysisResult(
            sample_id=sid,
            judgement={"correct": True},
            analysis_correct=True,
        )
        for sid in sample_ids
    ]

    # 压缩后 analysis 也全部 correct
    analysis_executor = PromptAwareAnalysisExecutor(compressed_correct=True)

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=analysis_prompt,
        line_limit=5,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="analysis",
        analysis_executor=analysis_executor,
        extraction_results=extraction_results,
        extraction_prompt=None,
        pre_compression_analysis_results=pre_analysis_results,
    )

    assert report.triggered is True
    assert report.accepted is True
    assert report.prompt_type == "analysis"
    assert result_prompt.id == "pa1_compressed"
    assert report.pre_compression_accuracy == 1.0
    assert report.post_compression_accuracy == 1.0
    assert report.broken_sample_ids == []


# ---------------------------------------------------------------------------
# Test 10: 缺少 executor 时拒绝
# ---------------------------------------------------------------------------


def test_no_executors_rejected():
    """extraction 模式下未提供 executor 时，rejected_reason='NO_EXECUTORS'。"""
    prompt = make_large_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
        extraction_executor=None,
        evaluation_executor=None,
        pre_compression_eval_records=make_eval_records(sample_ids, "correct"),
    )

    assert report.triggered is True
    assert report.accepted is False
    assert report.rejected_reason == "NO_EXECUTORS"
    assert result_prompt.id == prompt.id
