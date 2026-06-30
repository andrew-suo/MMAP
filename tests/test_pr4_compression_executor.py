"""PR4 单元测试：CompressionExecutor + SectionContributionTracker。

覆盖场景：
1. 未超限时不压缩：triggered=False, rejected_reason="NOT_NEEDED"。
2. 超行数限制触发确定性压缩：triggered=True。
3. 超字符限制触发确定性压缩：triggered=True。
4. immutable section 不被修改。
5. 压缩后 prompt 可正常渲染 to_markdown()。
6. CompressionReport 新字段完整填充。
7. analysis 模式确定性压缩。
8. 无 model_client 时仅确定性压缩（still_over_limit 正确）。
9. LLM section 级压缩 + 贡献度优先排序。
10. LLM 验证通过 → accepted。
11. LLM 验证失败 → rejected。
12. SectionContributionTracker EMA 更新。
13. SectionContributionTracker 优先级排序。
14. SectionContributionTracker 序列化往返。
"""

from __future__ import annotations

from pathlib import Path

from mmap_optimizer.executors.compression_executor import CompressionExecutor
from mmap_optimizer.patch.types import CompressionReport
from mmap_optimizer.data.sample import (
    SampleBatch,
    SampleSet,
    SampleSpec,
    SampleState,
)
from mmap_optimizer.prompt.section_contribution import SectionContributionTracker
from mmap_optimizer.prompt.structured_prompt import (
    PromptSection,
    StructuredPrompt,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPRESSION_PROMPT_PATH = str(REPO_ROOT / "prompts" / "prompt_compression.txt")
VALIDATION_PROMPT_PATH = str(REPO_ROOT / "prompts" / "prompt_compression_validation.txt")


# ---------------------------------------------------------------------------
# Mock model client
# ---------------------------------------------------------------------------


class _MockModelResponse:
    """Mock 模型响应。"""

    def __init__(self, raw_output: str) -> None:
        self.raw_output = raw_output


class MockModelClient:
    """Mock model client，根据 user message 区分压缩/验证调用。

    - 压缩调用（user message 含"压缩"）：返回 compression_output
    - 验证调用（user message 含"验证"）：返回 {"valid": ..., "reason": ...}
      可通过 validation_fail_after 控制第 N 次验证后开始返回 false。
    """

    def __init__(
        self,
        compression_output: str = "Compressed content",
        validation_valid: bool = True,
        validation_fail_after: int | None = None,
        validation_output: str | None = None,
        raise_on_validation: bool = False,
    ) -> None:
        self.compression_output = compression_output
        self.validation_valid = validation_valid
        self.validation_fail_after = validation_fail_after
        self.validation_output = validation_output
        self.raise_on_validation = raise_on_validation
        self.compression_calls = 0
        self.validation_calls = 0

    def complete(self, messages, model_config=None):
        user_msg = messages[-1]["content"] if messages else ""
        if "验证" in user_msg:
            self.validation_calls += 1
            if self.raise_on_validation:
                raise RuntimeError("mock validation call failed")
            if self.validation_output is not None:
                return _MockModelResponse(self.validation_output)
            if self.validation_fail_after is not None and self.validation_calls > self.validation_fail_after:
                return _MockModelResponse(
                    '{"valid": false, "reason": "mock validation fail"}'
                )
            valid_str = "true" if self.validation_valid else "false"
            return _MockModelResponse(
                f'{{"valid": {valid_str}, "reason": "mock validation"}}'
            )
        else:
            self.compression_calls += 1
            return _MockModelResponse(self.compression_output)


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


def make_large_unique_prompt() -> StructuredPrompt:
    """构造含多行唯一内容的 prompt（确定性压缩无法大幅缩减）。"""
    lines = [f"Unique rule number {i} for testing purposes" for i in range(20)]
    content = "\n".join(lines)
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


def make_prompt_with_duplicates_and_unique() -> StructuredPrompt:
    """构造含重复行和唯一行的 prompt（确定性压缩可去重但仍超限）。"""
    content = (
        "Duplicate line\n"
        "Duplicate line\n"
        "\n"
        "Unique rule one for testing\n"
        "Unique rule two for testing\n"
        "Unique rule three for testing\n"
        "Unique rule four for testing\n"
        "Unique rule five for testing\n"
        "Unique rule six for testing\n"
        "Unique rule seven for testing\n"
        "Unique rule eight for testing\n"
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


def make_prompt_with_immutable_bullets() -> StructuredPrompt:
    """构造 immutable bullets 和 mutable bullets 混合的 prompt。"""
    immutable_section = PromptSection(
        id="section_immutable",
        title="Fixed Rules",
        level=1,
        content="Keep content",
        bullets=["A", "A", "B"],
        mutable=False,
    )
    mutable_section = PromptSection(
        id="section_mutable",
        title="Mutable Rules",
        level=1,
        content="Compress me\nCompress me\n\n\nStill compress me",
        bullets=["X", "X", "Y"],
        mutable=True,
    )
    return StructuredPrompt(
        id="p_bullets",
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


# ---------------------------------------------------------------------------
# Tests 1-8: 确定性压缩（无 model_client）
# ---------------------------------------------------------------------------


def test_not_over_limit_no_compression():
    """prompt 未超行数和字符限制时，triggered=False, rejected_reason='NOT_NEEDED'。"""
    prompt = make_large_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=1000,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
    )

    assert report.triggered is False
    assert report.rejected_reason == "NOT_NEEDED"
    assert report.accepted is False
    assert result_prompt.id == prompt.id
    assert report.line_count_before == report.line_count_after
    assert report.char_count_before == report.char_count_after


def test_over_line_limit_triggers_compression():
    """prompt 超行数限制时，triggered=True，确定性压缩减少行数。"""
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
    )

    assert report.triggered is True
    assert report.line_count_after < report.line_count_before
    # 无 model_client → 确定性压缩后自动接受
    assert report.accepted is True
    assert report.validation_passed is True
    assert report.validation_reasons == ["deterministic only (no model_client)"]


def test_over_char_limit_triggers_compression():
    """prompt 超字符限制时，triggered=True，确定性压缩减少字符数。"""
    prompt = make_long_char_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    md = prompt.to_markdown()
    assert len(md.splitlines()) <= 10  # 未超行数限制

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=1000,
        char_limit=150,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
    )

    assert report.triggered is True
    assert report.char_count_after < report.char_count_before
    assert report.accepted is True


def test_immutable_section_not_modified():
    """压缩后 immutable section 内容不变，mutable section 被压缩。"""
    prompt = make_prompt_with_immutable()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    orig_immutable = prompt.get_section_by_id("section_immutable")
    orig_immutable_content = orig_immutable.content

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
    )

    assert report.accepted is True
    assert report.warnings == []

    comp_immutable = result_prompt.get_section_by_id("section_immutable")
    assert comp_immutable.content == orig_immutable_content

    orig_mutable = prompt.get_section_by_id("section_mutable")
    comp_mutable = result_prompt.get_section_by_id("section_mutable")
    assert len(comp_mutable.content.splitlines()) < len(orig_mutable.content.splitlines())


def test_immutable_section_bullets_not_modified():
    """immutable section 的 bullets 不应被确定性压缩去重。"""
    prompt = make_prompt_with_immutable_bullets()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=3,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
    )

    assert report.accepted is True
    comp_immutable = result_prompt.get_section_by_id("section_immutable")
    comp_mutable = result_prompt.get_section_by_id("section_mutable")
    assert comp_immutable.bullets == ["A", "A", "B"]
    assert comp_mutable.bullets == ["X", "Y"]


def test_compressed_prompt_can_render():
    """压缩后的 prompt 可正常调用 to_markdown() 不报错。"""
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
    )

    assert report.accepted is True

    markdown = result_prompt.to_markdown()
    assert isinstance(markdown, str)
    assert len(markdown) > 0
    assert result_prompt.raw_markdown == markdown
    orig_md = prompt.to_markdown()
    assert len(markdown.splitlines()) < len(orig_md.splitlines())


def test_compression_report_fields_complete():
    """接受的 CompressionReport 所有新字段被正确填充。"""
    prompt = make_large_prompt()
    sample_ids = ["s1", "s2", "s3"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=10,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
    )

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
    # 新字段
    assert report.validation_passed is True
    assert isinstance(report.validation_reasons, list)
    assert len(report.validation_reasons) > 0
    assert isinstance(report.compressed_sections, list)
    assert isinstance(report.warnings, list)
    assert report.warnings == []
    assert report.still_over_limit is False

    # to_dict / from_dict 往返
    d = report.to_dict()
    assert d["id"] == "compression_extraction_p1"
    assert d["triggered"] is True
    assert d["accepted"] is True
    assert d["validation_passed"] is True
    assert "validation_reasons" in d
    assert "compressed_sections" in d

    restored = CompressionReport.from_dict(d)
    assert restored.id == report.id
    assert restored.triggered is True
    assert restored.accepted is True
    assert restored.validation_passed is True
    assert restored.validation_reasons == report.validation_reasons
    assert restored.compressed_sections == report.compressed_sections
    assert restored.compressed_prompt_id == "p1_compressed"
    assert restored.still_over_limit is False


def test_analysis_mode_compression():
    """analysis 模式下确定性压缩正常工作。"""
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

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=analysis_prompt,
        line_limit=5,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        mode="analysis",
    )

    assert report.triggered is True
    assert report.accepted is True
    assert report.prompt_type == "analysis"
    assert result_prompt.id == "pa1_compressed"
    assert report.validation_passed is True


def test_no_model_client_deterministic_only_still_over_limit():
    """无 model_client + 确定性压缩无法降至限内 → accepted=True, still_over_limit=True。"""
    prompt = make_large_unique_prompt()  # 20 行唯一内容，确定性压缩无法缩减
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    executor = CompressionExecutor()
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=100000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
    )

    assert report.triggered is True
    assert report.accepted is True  # 无 model_client 自动接受
    assert report.validation_passed is True
    assert report.validation_reasons == ["deterministic only (no model_client)"]
    assert report.still_over_limit is True  # 仍超限


# ---------------------------------------------------------------------------
# Tests 9-11: LLM 压缩路径（mock model_client）
# ---------------------------------------------------------------------------


def test_llm_section_compression_with_tracker():
    """mock model_client + 贡献度追踪：section 级 LLM 压缩成功。"""
    prompt = make_large_unique_prompt()  # 20 行唯一内容
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    # 贡献度追踪器：section_1 贡献度为负（低贡献，优先压缩）
    tracker = SectionContributionTracker(alpha=0.3)
    tracker._ema = {"section_1": -0.5}

    mock_client = MockModelClient(
        compression_output="Compressed: all rules combined into one.",
        validation_valid=True,
    )

    executor = CompressionExecutor(
        model_client=mock_client,
        compression_prompt_path=COMPRESSION_PROMPT_PATH,
        validation_prompt_path=VALIDATION_PROMPT_PATH,
    )
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=100000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
        contribution_tracker=tracker,
    )

    assert report.triggered is True
    assert mock_client.compression_calls > 0  # LLM 压缩被调用
    assert mock_client.validation_calls > 0  # LLM 验证被调用
    assert "section_1" in report.compressed_sections
    assert report.line_count_after < report.line_count_before
    # 压缩后应降至限内
    assert report.line_count_after <= 5
    assert report.accepted is True
    assert report.validation_passed is True


def test_llm_validation_pass():
    """mock model_client 验证通过 → accepted=True。"""
    prompt = make_large_unique_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    mock_client = MockModelClient(
        compression_output="Short compressed content.",
        validation_valid=True,
    )

    executor = CompressionExecutor(
        model_client=mock_client,
        compression_prompt_path=COMPRESSION_PROMPT_PATH,
        validation_prompt_path=VALIDATION_PROMPT_PATH,
    )
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=100000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
    )

    assert report.triggered is True
    assert report.accepted is True
    assert report.validation_passed is True
    assert report.rejected_reason is None


def test_llm_validation_fail():
    """mock model_client 验证失败 → accepted=False, rejected_reason='VALIDATION_FAILED'。

    策略：validation_fail_after=1 使第 1 次验证（section 级）通过、第 2 次（prompt 级）失败。
    section 压缩成功降至限内后，_llm_validate_prompt 验证失败 → 拒绝。
    """
    prompt = make_large_unique_prompt()  # 20 行唯一内容
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    mock_client = MockModelClient(
        compression_output="Short compressed content.",
        validation_valid=True,
        validation_fail_after=1,  # 第 1 次验证通过，第 2 次失败
    )

    executor = CompressionExecutor(
        model_client=mock_client,
        compression_prompt_path=COMPRESSION_PROMPT_PATH,
        validation_prompt_path=VALIDATION_PROMPT_PATH,
    )
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=100000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
    )

    assert report.triggered is True
    assert report.accepted is False
    assert report.rejected_reason == "VALIDATION_FAILED"
    assert result_prompt.id == prompt.id  # 返回原 prompt
    assert mock_client.validation_calls >= 2  # 至少 2 次验证调用


def test_prompt_level_llm_compression_rejects_deleted_section(monkeypatch):
    """prompt 级 LLM 压缩删 section 时，应以 CONSTRAINT_VIOLATION 拒绝。"""
    prompt = make_prompt_with_immutable()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    mock_client = MockModelClient(
        compression_output="# Fixed Rules\nOnly one section remains",
        validation_valid=True,
    )
    executor = CompressionExecutor(
        model_client=mock_client,
        compression_prompt_path=COMPRESSION_PROMPT_PATH,
        validation_prompt_path=VALIDATION_PROMPT_PATH,
    )

    monkeypatch.setattr(
        executor,
        "_llm_compress_sections",
        lambda prompt, line_limit, char_limit, contribution_tracker: (
            prompt,
            len(prompt.to_markdown().splitlines()),
            len(prompt.to_markdown()),
            [],
        ),
    )

    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=1,
        char_limit=100000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
    )

    assert report.triggered is True
    assert report.accepted is False
    assert report.rejected_reason == "CONSTRAINT_VIOLATION"
    assert "section section_mutable was deleted" in report.warnings
    assert result_prompt.id == prompt.id


def test_prompt_level_llm_compression_rejects_immutable_bullet_change(monkeypatch):
    """prompt 级 LLM 压缩修改 immutable bullets 时，应被拒绝。"""
    prompt = make_prompt_with_immutable_bullets()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    mock_client = MockModelClient(
        compression_output="unused",
        validation_valid=True,
    )
    executor = CompressionExecutor(
        model_client=mock_client,
        compression_prompt_path=COMPRESSION_PROMPT_PATH,
        validation_prompt_path=VALIDATION_PROMPT_PATH,
    )

    monkeypatch.setattr(
        executor,
        "_llm_compress_sections",
        lambda prompt, line_limit, char_limit, contribution_tracker: (
            prompt,
            len(prompt.to_markdown().splitlines()),
            len(prompt.to_markdown()),
            [],
        ),
    )
    bad_prompt = make_prompt_with_immutable_bullets()
    bad_prompt.id = f"{prompt.id}_llm_compressed"
    bad_prompt.version = prompt.version + 1
    bad_prompt.get_section_by_id("section_immutable").bullets = ["A", "B"]
    monkeypatch.setattr(
        executor,
        "_llm_compress_prompt",
        lambda prompt, line_limit, char_limit: (
            bad_prompt,
            len(bad_prompt.to_markdown().splitlines()),
            len(bad_prompt.to_markdown()),
        ),
    )

    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=1,
        char_limit=100000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
    )

    assert report.accepted is False
    assert report.rejected_reason == "CONSTRAINT_VIOLATION"
    assert "immutable section section_immutable bullets were modified" in report.warnings
    assert result_prompt.id == prompt.id


def test_llm_validation_parse_failure_rejects_compression(monkeypatch):
    """validation JSON 不可解析时，应拒绝压缩结果而不是放行。"""
    prompt = make_large_unique_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    mock_client = MockModelClient(validation_output="not-json")
    executor = CompressionExecutor(
        model_client=mock_client,
        compression_prompt_path=COMPRESSION_PROMPT_PATH,
        validation_prompt_path=VALIDATION_PROMPT_PATH,
    )

    monkeypatch.setattr(
        executor,
        "_llm_compress_sections",
        lambda prompt, line_limit, char_limit, contribution_tracker: (
            prompt,
            len(prompt.to_markdown().splitlines()),
            len(prompt.to_markdown()),
            [],
        ),
    )
    valid_compressed_prompt = make_large_unique_prompt()
    valid_compressed_prompt.id = f"{prompt.id}_llm_compressed"
    valid_compressed_prompt.version = prompt.version + 1
    valid_compressed_prompt.get_section_by_id("section_1").content = "Short compressed content."
    monkeypatch.setattr(
        executor,
        "_llm_compress_prompt",
        lambda prompt, line_limit, char_limit: (
            valid_compressed_prompt,
            len(valid_compressed_prompt.to_markdown().splitlines()),
            len(valid_compressed_prompt.to_markdown()),
        ),
    )

    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=100000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
    )

    assert report.accepted is False
    assert report.rejected_reason == "VALIDATION_FAILED"
    assert any("validation_parse_failed" in reason for reason in report.validation_reasons)
    assert result_prompt.id == prompt.id


def test_llm_validation_call_failure_rejects_compression(monkeypatch):
    """validation 调用报错时，应拒绝压缩结果而不是放行。"""
    prompt = make_large_unique_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = make_sample_set(sample_ids)
    batch = make_batch(sample_ids)

    mock_client = MockModelClient(raise_on_validation=True)
    executor = CompressionExecutor(
        model_client=mock_client,
        compression_prompt_path=COMPRESSION_PROMPT_PATH,
        validation_prompt_path=VALIDATION_PROMPT_PATH,
    )

    monkeypatch.setattr(
        executor,
        "_llm_compress_sections",
        lambda prompt, line_limit, char_limit, contribution_tracker: (
            prompt,
            len(prompt.to_markdown().splitlines()),
            len(prompt.to_markdown()),
            [],
        ),
    )
    valid_compressed_prompt = make_large_unique_prompt()
    valid_compressed_prompt.id = f"{prompt.id}_llm_compressed"
    valid_compressed_prompt.version = prompt.version + 1
    valid_compressed_prompt.get_section_by_id("section_1").content = "Short compressed content."
    monkeypatch.setattr(
        executor,
        "_llm_compress_prompt",
        lambda prompt, line_limit, char_limit: (
            valid_compressed_prompt,
            len(valid_compressed_prompt.to_markdown().splitlines()),
            len(valid_compressed_prompt.to_markdown()),
        ),
    )

    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=100000,
        batch=batch,
        sample_set=sample_set,
        mode="extraction",
    )

    assert report.accepted is False
    assert report.rejected_reason == "VALIDATION_FAILED"
    assert any("validation_call_failed" in reason for reason in report.validation_reasons)
    assert result_prompt.id == prompt.id


# ---------------------------------------------------------------------------
# Tests 12-14: SectionContributionTracker
# ---------------------------------------------------------------------------


def test_section_contribution_tracker_update():
    """EMA 更新：correct 样本引用的 section 贡献度为正，incorrect 为负。"""
    tracker = SectionContributionTracker(alpha=0.3)

    batch_attribution = {
        "s1": [{"section_id": "sec_a", "reason": "used"}],
        "s2": [{"section_id": "sec_a", "reason": "used"}, {"section_id": "sec_b", "reason": "used"}],
        "s3": [{"section_id": "sec_b", "reason": "used"}],
    }
    batch_results = {
        "s1": True,   # correct → sec_a +1
        "s2": True,   # correct → sec_a +1, sec_b +1
        "s3": False,  # incorrect → sec_b -1
    }

    tracker.update(batch_attribution, batch_results)

    # sec_a: 2 correct, 0 incorrect → frequency = (2-0)/3 = 0.667
    # ema = 0.3 * 0.667 + 0.7 * 0 = 0.2
    assert tracker.get_contribution("sec_a") > 0
    assert abs(tracker.get_contribution("sec_a") - (0.3 * (2 / 3))) < 0.01

    # sec_b: 1 correct, 1 incorrect → frequency = (1-1)/3 = 0
    # ema = 0.3 * 0 + 0.7 * 0 = 0
    assert abs(tracker.get_contribution("sec_b")) < 0.01

    # 未引用的 section 贡献度为 0
    assert tracker.get_contribution("sec_unknown") == 0.0


def test_section_contribution_tracker_priority_order():
    """低贡献 section 排在前面，优先压缩。"""
    tracker = SectionContributionTracker(alpha=0.3)
    tracker._ema = {
        "sec_high": 0.8,
        "sec_low": -0.5,
        "sec_mid": 0.1,
        "sec_zero": 0.0,
    }

    ordered = tracker.get_priority_order(["sec_high", "sec_low", "sec_mid", "sec_zero"])

    # 升序排列：sec_low(-0.5) < sec_zero(0.0) < sec_mid(0.1) < sec_high(0.8)
    assert ordered == ["sec_low", "sec_zero", "sec_mid", "sec_high"]

    # 部分排序
    ordered_partial = tracker.get_priority_order(["sec_high", "sec_low"])
    assert ordered_partial == ["sec_low", "sec_high"]

    # 空列表
    assert tracker.get_priority_order([]) == []


def test_section_contribution_tracker_serialization():
    """to_dict / from_dict 往返一致。"""
    tracker = SectionContributionTracker(alpha=0.3)
    tracker._ema = {"sec_a": 0.5, "sec_b": -0.3, "sec_c": 0.0}

    d = tracker.to_dict()
    assert d == {"sec_a": 0.5, "sec_b": -0.3, "sec_c": 0.0}

    restored = SectionContributionTracker.from_dict(d, alpha=0.3)
    assert restored.alpha == 0.3
    assert restored._ema == {"sec_a": 0.5, "sec_b": -0.3, "sec_c": 0.0}
    assert restored.get_contribution("sec_a") == 0.5
    assert restored.get_contribution("sec_b") == -0.3

    # 空字典
    empty = SectionContributionTracker()
    assert empty.to_dict() == {}
    restored_empty = SectionContributionTracker.from_dict({})
    assert restored_empty.get_contribution("anything") == 0.0


def test_section_contribution_tracker_ema_smoothing():
    """多轮 EMA 平滑：alpha 越大越看重近期数据。"""
    tracker = SectionContributionTracker(alpha=0.3)

    # 第一轮：全 correct，sec_a 频率 = 1.0
    tracker.update(
        {"s1": [{"section_id": "sec_a"}]},
        {"s1": True},
    )
    first = tracker.get_contribution("sec_a")
    assert abs(first - (0.3 * 1.0)) < 0.01  # 0.3

    # 第二轮：全 incorrect，sec_a 频率 = -1.0
    tracker.update(
        {"s1": [{"section_id": "sec_a"}]},
        {"s1": False},
    )
    second = tracker.get_contribution("sec_a")
    # ema = 0.3 * (-1) + 0.7 * 0.3 = -0.3 + 0.21 = -0.09
    assert abs(second - (-0.09)) < 0.01
    assert second < first  # 贡献度下降
