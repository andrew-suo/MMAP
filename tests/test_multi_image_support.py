"""多图样本支持测试。

验证：
1. 抽取阶段多图样本图片不重复发送（修复双倍图片 bug）。
2. 分析阶段 execute 带图（complete_multimodal 被调用且 assets 含样本图片）。
3. 分析阶段 reflect 带图。
4. fewshot _select_difficult_samples 的 input_images 仅含非空图片资产。
"""

from __future__ import annotations

from typing import Any

import pytest

from mmap_optimizer.model.client import ModelResponse
from mmap_optimizer.model.openai_compatible import OpenAICompatibleClient
from mmap_optimizer.refactored.executors.analysis_executor import AnalysisExecutor
from mmap_optimizer.refactored.executors.extraction_executor import ExtractionExecutor
from mmap_optimizer.refactored.extraction_prompt_optimization_stage import (
    AnalysisResult,
    ExtractionResult,
)
from mmap_optimizer.refactored.fewshot_optimization_phase import (
    FewshotConfig,
    FewshotMetrics,
    FewshotOptimizationPhase,
)
from mmap_optimizer.refactored.sample import (
    SampleAsset,
    SampleBatch,
    SampleSet,
    SampleSpec,
    SampleState,
)
from mmap_optimizer.refactored.structured_prompt import (
    PromptSection,
    StructuredPrompt,
)


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


class RecordingClient(OpenAICompatibleClient):
    """记录 _messages_with_assets 后消息的 client，返回 ModelResponse。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.prepared_messages: list[dict[str, Any]] | None = None
        self.last_assets: list[Any] | None = None
        self.response_output = '{"is_correct": true, "error_reason": null}'

    def complete_multimodal(
        self,
        messages: list[dict[str, Any]],
        assets: list[Any] | None = None,
        model_config: dict[str, Any] | None = None,
        response_format: Any | None = None,
    ) -> ModelResponse:
        self.last_assets = list(assets) if assets else []
        self.prepared_messages = self._messages_with_assets(
            [dict(m) for m in messages], self.last_assets
        )
        return ModelResponse(raw_output=self.response_output)


def make_extraction_prompt() -> StructuredPrompt:
    return StructuredPrompt(
        id="test_extraction_prompt",
        prompt_type="extraction",
        sections=[
            PromptSection(id="s1", title="Task", level=1, content="Extract the result."),
            PromptSection(id="s2", title="Schema", level=1, content='{"result":"string"}'),
        ],
        raw_markdown="# Task\n\nExtract the result.\n\n# Schema\n\n" '{"result":"string"}',
    )


def make_analysis_prompt() -> StructuredPrompt:
    return StructuredPrompt(
        id="test_analysis_prompt",
        prompt_type="analysis",
        sections=[
            PromptSection(id="a1", title="Analysis", level=1, content="Judge extraction."),
        ],
        raw_markdown="# Analysis\n\nJudge extraction.",
    )


# ---------------------------------------------------------------------------
# 1. 抽取阶段多图不重复
# ---------------------------------------------------------------------------


def test_extraction_multi_image_no_duplication():
    """抽取阶段多图样本：image_url parts 数 == 图片数，不是 2 倍。"""
    client = RecordingClient(base_url="https://example.test")
    executor = ExtractionExecutor(model_client=client)

    prompt = make_extraction_prompt()
    spec = SampleSpec(
        id="s_multi",
        input={"text": "multi image sample"},
        ground_truth={"result": "OK"},
        assets=[
            SampleAsset(id="img1", sample_id="s_multi", type="image", uri="https://example.test/1.png"),
            SampleAsset(id="img2", sample_id="s_multi", type="image", uri="https://example.test/2.png"),
        ],
    )

    executor._execute_single(prompt, spec)

    msgs = client.prepared_messages
    assert msgs is not None
    # system + user = 2
    assert len(msgs) == 2
    user_msg = msgs[1]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)
    image_parts = [p for p in user_msg["content"] if p["type"] == "image_url"]
    # 关键断言：2 张图，不是 4 张（修复双倍 bug）
    assert len(image_parts) == 2, (
        f"expected 2 image_url parts (no duplication), got {len(image_parts)}"
    )
    urls = {p["image_url"]["url"] for p in image_parts}
    assert urls == {"https://example.test/1.png", "https://example.test/2.png"}


def test_extraction_single_image_no_duplication():
    """抽取阶段单图样本：image_url parts 数 == 1，不是 2。"""
    client = RecordingClient(base_url="https://example.test")
    executor = ExtractionExecutor(model_client=client)

    prompt = make_extraction_prompt()
    spec = SampleSpec(
        id="s_single",
        input={"text": "single image"},
        ground_truth={"result": "OK"},
        assets=[SampleAsset(id="img1", sample_id="s_single", type="image", uri="https://example.test/only.png")],
    )

    executor._execute_single(prompt, spec)

    msgs = client.prepared_messages
    assert msgs is not None
    user_msg = msgs[1]
    image_parts = [p for p in user_msg["content"] if p["type"] == "image_url"]
    assert len(image_parts) == 1, f"expected 1 image_url part, got {len(image_parts)}"


def test_extraction_no_image_user_message_is_string():
    """无图样本：user 消息 content 仍为纯文本字符串。"""
    client = RecordingClient(base_url="https://example.test")
    executor = ExtractionExecutor(model_client=client)

    prompt = make_extraction_prompt()
    spec = SampleSpec(id="s_text", input={"text": "text only"}, ground_truth={"result": "OK"})

    executor._execute_single(prompt, spec)

    msgs = client.prepared_messages
    assert msgs is not None
    user_msg = msgs[1]
    # 无 assets 时 _messages_with_assets 原样返回，content 仍为字符串
    assert isinstance(user_msg["content"], str)


# ---------------------------------------------------------------------------
# 2. 分析阶段 execute 带图
# ---------------------------------------------------------------------------


def test_analysis_executor_carries_images():
    """分析阶段 execute 带图：complete_multimodal 被调用且 assets 含样本图片。"""
    client = RecordingClient(base_url="https://example.test")
    executor = AnalysisExecutor(model_client=client)

    extraction_prompt = make_extraction_prompt()
    analysis_prompt = make_analysis_prompt()
    spec = SampleSpec(
        id="s_ana",
        input={"text": "analysis sample"},
        ground_truth={"result": "OK"},
        assets=[
            SampleAsset(id="img1", sample_id="s_ana", type="image", uri="https://example.test/a.png"),
            SampleAsset(id="img2", sample_id="s_ana", type="image", uri="https://example.test/b.png"),
        ],
    )
    extraction_result = ExtractionResult(
        sample_id="s_ana",
        raw_output='{"result":"OK"}',
        parsed_output={"result": "OK"},
        status="correct",
    )

    executor.execute(analysis_prompt, extraction_prompt, extraction_result, spec)

    # 断言 complete_multimodal 被调用且 assets 含 2 张图片
    assert client.last_assets is not None
    assert len(client.last_assets) == 2, (
        f"expected 2 image assets, got {len(client.last_assets)}"
    )
    assert all(a.type == "image" for a in client.last_assets)


def test_analysis_executor_no_image_empty_assets():
    """分析阶段无图样本：assets 为空列表（仍走 complete_multimodal）。"""
    client = RecordingClient(base_url="https://example.test")
    executor = AnalysisExecutor(model_client=client)

    extraction_prompt = make_extraction_prompt()
    analysis_prompt = make_analysis_prompt()
    spec = SampleSpec(id="s_no_img", input={"text": "no image"}, ground_truth={"result": "OK"})
    extraction_result = ExtractionResult(
        sample_id="s_no_img",
        raw_output='{"result":"OK"}',
        parsed_output={"result": "OK"},
        status="correct",
    )

    executor.execute(analysis_prompt, extraction_prompt, extraction_result, spec)

    assert client.last_assets is not None
    assert client.last_assets == []


# ---------------------------------------------------------------------------
# 3. 分析阶段 reflect 带图
# ---------------------------------------------------------------------------


def test_analysis_reflect_carries_images():
    """分析阶段 reflect 带图。"""
    client = RecordingClient(base_url="https://example.test")
    client.response_output = (
        '{"error_reason":"misjudged",'
        '"patch_suggestion":{"target_section":"s1","operation":"replace","content":"fix"},'
        '"notes":[]}'
    )
    executor = AnalysisExecutor(model_client=client)

    analysis_prompt = make_analysis_prompt()
    spec = SampleSpec(
        id="s_reflect",
        input={"text": "reflect sample"},
        ground_truth={"result": "OK"},
        assets=[SampleAsset(id="img1", sample_id="s_reflect", type="image", uri="https://example.test/r.png")],
    )
    extraction_result = ExtractionResult(
        sample_id="s_reflect",
        raw_output='{"result":"OK"}',
        parsed_output={"result": "OK"},
        status="correct",
    )
    analysis_result = AnalysisResult(
        sample_id="s_reflect",
        judgement={},
        analysis_correct=False,
        error_reason="misjudged",
        patch_suggestion=None,
    )

    executor.reflect(analysis_prompt, extraction_result, analysis_result, spec)

    assert client.last_assets is not None
    assert len(client.last_assets) == 1
    assert client.last_assets[0].type == "image"


# ---------------------------------------------------------------------------
# 4. fewshot input_images 过滤
# ---------------------------------------------------------------------------


def test_fewshot_select_difficult_samples_filters_input_images(tmp_path):
    """_select_difficult_samples 的 input_images 仅含非空图片资产。"""
    assets = [
        SampleAsset(id="img_uri", sample_id="s1", type="image", uri="https://example.test/a.png"),
        SampleAsset(id="img_local", sample_id="s1", type="image", local_path=str(tmp_path / "b.png")),
        SampleAsset(id="audio", sample_id="s1", type="audio", uri="https://example.test/a.mp3"),
        SampleAsset(id="img_empty", sample_id="s1", type="image"),
    ]
    spec = SampleSpec(
        id="s1",
        input={"q": "x"},
        ground_truth={"result": "y"},
        assets=assets,
    )
    sample_set = SampleSet()
    sample_set.add_spec(spec)
    sample_set.states["s1"] = SampleState(sample_id="s1")
    sample_set.states["s1"].difficulty_score = 0.9

    config = FewshotConfig(slot_count=1, batch_size=1)
    phase = FewshotOptimizationPhase(
        config=config,
        extraction_prompt=make_extraction_prompt(),
        sample_set=sample_set,
        output_dir=tmp_path,
    )

    batch = SampleBatch(
        id="b1",
        phase="fewshot_optimization",
        iteration=1,
        sample_ids=["s1"],
        sampler_name="test",
    )
    examples = phase._select_difficult_samples(batch, FewshotMetrics())

    assert len(examples) == 1
    images = examples[0].input_images
    # 仅含 2 个非空图片资产，非图片资产和空资产被过滤
    assert len(images) == 2, f"expected 2 image paths, got {len(images)}: {images}"
    assert "https://example.test/a.png" in images
    assert str(tmp_path / "b.png") in images
    assert all(img for img in images)


def test_fewshot_select_difficult_samples_no_image_assets(tmp_path):
    """样本无图片资产时，input_images 为空列表。"""
    spec = SampleSpec(
        id="s_no_img",
        input={"q": "x"},
        ground_truth={"result": "y"},
        assets=[SampleAsset(id="audio1", sample_id="s_no_img", type="audio", uri="https://x/a.mp3")],
    )
    sample_set = SampleSet()
    sample_set.add_spec(spec)
    sample_set.states["s_no_img"] = SampleState(sample_id="s_no_img")
    sample_set.states["s_no_img"].difficulty_score = 0.5

    config = FewshotConfig(slot_count=1, batch_size=1)
    phase = FewshotOptimizationPhase(
        config=config,
        extraction_prompt=make_extraction_prompt(),
        sample_set=sample_set,
        output_dir=tmp_path,
    )

    batch = SampleBatch(
        id="b1",
        phase="fewshot_optimization",
        iteration=1,
        sample_ids=["s_no_img"],
        sampler_name="test",
    )
    examples = phase._select_difficult_samples(batch, FewshotMetrics())

    assert len(examples) == 1
    assert examples[0].input_images == []
