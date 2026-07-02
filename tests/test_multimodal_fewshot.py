"""多模态 few-shot 修复测试。

验证：
1. 多模态 few-shot 走"对话轮次注入"路径，图片作为 image_url content part 内联。
2. 文本 few-shot 保持原行为（写进 system prompt），向后兼容。
3. ``_image_string_to_url`` 对本地文件 / HTTP URI 的转换正确。
4. ``_select_difficult_samples`` 构造的 ``input_images`` 仅含非空图片资产。
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from mmap_optimizer.data.sample import (
    SampleAsset,
    SampleBatch,
    SampleSet,
    SampleSpec,
    SampleState,
    SampleTrace,
)
from mmap_optimizer.executors.fewshot_executor import FewshotExecutor
from mmap_optimizer.executors.extraction_executor import ExtractionExecutor
from mmap_optimizer.model.client import ModelResponse
from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.model.openai_compatible import OpenAICompatibleClient
from mmap_optimizer.phases.fewshot_optimization import (
    FewshotConfig,
    FewshotExample,
    FewshotMetrics,
    FewshotOptimizationPhase,
)
from mmap_optimizer.prompt.structured_prompt import (
    PromptSection,
    StructuredPrompt,
)


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


class RecordingClient(OpenAICompatibleClient):
    """记录 ``_messages_with_assets`` 后消息的 client，不发起真实请求。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.prepared_messages: list[dict[str, Any]] | None = None
        self.last_assets: list[Any] | None = None
        self.response_output = '{"result": "OK"}'

    def complete_multimodal(
        self,
        messages: list[dict[str, Any]],
        assets: list[Any],
        model_config: dict[str, Any] | None = None,
        response_format: Any | None = None,
    ) -> ModelResponse:
        self.last_assets = list(assets) if assets else []
        self.prepared_messages = self._messages_with_assets(
            [dict(m) for m in messages],
            self.last_assets,
        )
        return ModelResponse(raw_output=self.response_output)


def make_extraction_prompt() -> StructuredPrompt:
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


def make_spec(sample_id: str, assets: list[SampleAsset] | None = None) -> SampleSpec:
    return SampleSpec(
        id=sample_id,
        input={"sample_id": sample_id, "question": "What is in the image?"},
        ground_truth={"result": "cat"},
        assets=assets or [],
    )


# ---------------------------------------------------------------------------
# 1. 多模态 few-shot 消息结构
# ---------------------------------------------------------------------------


def test_multimodal_fewshot_uses_conversation_turns_with_inline_images():
    """多模态 few-shot：示例渲染为 user/assistant 轮次，图片内联为 image_url。"""
    client = RecordingClient(base_url="https://example.test")
    executor = ExtractionExecutor(model_client=client)

    prompt = make_extraction_prompt()
    spec = make_spec(
        "current_sample",
        assets=[SampleAsset(id="cur_img", sample_id="current_sample", type="image",
                             uri="https://example.test/current.png", mime_type="image/png")],
    )
    examples = [
        FewshotExample(
            id="fewshot_ex1",
            sample_id="ex1",
            input_text="What animal?",
            output_text='{"result": "dog"}',
            input_images=["https://example.test/ex1.png"],
        ),
        FewshotExample(
            id="fewshot_ex2",
            sample_id="ex2",
            input_text="What color?",
            output_text='{"result": "red"}',
            input_images=["https://example.test/ex2a.png", "https://example.test/ex2b.png"],
        ),
    ]

    executor._execute_single(prompt, spec, examples)

    msgs = client.prepared_messages
    assert msgs is not None
    # system + (user, assistant) * 2 + 当前样本 user = 6
    assert len(msgs) == 6
    # 1) system 不含 few-shot section
    assert msgs[0]["role"] == "system"
    assert "# Few-shot Examples" not in msgs[0]["content"]
    # 2) 示例 1：user 含 1 text + 1 image_url；assistant 含输出
    ex1_user = msgs[1]
    assert ex1_user["role"] == "user"
    assert isinstance(ex1_user["content"], list)
    types_1 = [p["type"] for p in ex1_user["content"]]
    assert types_1.count("text") == 1
    assert types_1.count("image_url") == 1
    assert "Few-shot Example Input" in ex1_user["content"][0]["text"]
    assert ex1_user["content"][1]["image_url"]["url"] == "https://example.test/ex1.png"
    assert msgs[2]["role"] == "assistant"
    assert "dog" in msgs[2]["content"]
    # 3) 示例 2：user 含 1 text + 2 image_url
    ex2_user = msgs[3]
    assert ex2_user["role"] == "user"
    types_2 = [p["type"] for p in ex2_user["content"]]
    assert types_2.count("text") == 1
    assert types_2.count("image_url") == 2
    # 4) 当前样本 user 消息：图片由 assets 注入，应含 text + image_url
    current_user = msgs[5]
    assert current_user["role"] == "user"
    assert isinstance(current_user["content"], list)
    current_types = [p["type"] for p in current_user["content"]]
    assert current_types.count("text") >= 1
    assert current_types.count("image_url") == 1
    assert current_user["content"][-1]["image_url"]["url"] == "https://example.test/current.png"


def test_mixed_examples_all_become_turns_when_any_has_images():
    """只要任一示例含图片，所有示例（含纯文本）都走对话轮次路径。"""
    client = RecordingClient(base_url="https://example.test")
    executor = ExtractionExecutor(model_client=client)

    prompt = make_extraction_prompt()
    spec = make_spec("current_sample")
    examples = [
        FewshotExample(
            id="fewshot_text_only",
            sample_id="text_ex",
            input_text="text only example",
            output_text='{"result": "bird"}',
            input_images=[],
        ),
        FewshotExample(
            id="fewshot_with_img",
            sample_id="img_ex",
            input_text="image example",
            output_text='{"result": "fish"}',
            input_images=["https://example.test/img.png"],
        ),
    ]

    executor._execute_single(prompt, spec, examples)

    msgs = client.prepared_messages
    # system + (user, assistant) * 2 + 当前样本 user = 6
    assert len(msgs) == 6
    # 纯文本示例的 user 消息仍为 list content（只含 text part，无 image_url）
    text_only_user = msgs[1]
    assert text_only_user["role"] == "user"
    assert isinstance(text_only_user["content"], list)
    assert all(p["type"] == "text" for p in text_only_user["content"])
    # system 不含 few-shot section
    assert "# Few-shot Examples" not in msgs[0]["content"]


# ---------------------------------------------------------------------------
# 2. 文本 few-shot 向后兼容
# ---------------------------------------------------------------------------


def test_text_fewshot_stays_in_system_prompt():
    """无图片的 few-shot 仍写进 system prompt，消息总数为 2。"""
    client = RecordingClient(base_url="https://example.test")
    executor = ExtractionExecutor(model_client=client)

    prompt = make_extraction_prompt()
    spec = make_spec("current_sample")
    examples = [
        FewshotExample(
            id="fewshot_text1",
            sample_id="t1",
            input_text="text example",
            output_text='{"result": "dog"}',
            input_images=[],
        ),
    ]

    executor._execute_single(prompt, spec, examples)

    msgs = client.prepared_messages
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "# Few-shot Examples" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"


def test_multimodal_fewshot_assistant_message_can_include_rationale():
    client = RecordingClient(base_url="https://example.test")
    executor = ExtractionExecutor(model_client=client)

    prompt = make_extraction_prompt()
    spec = make_spec("current_sample")
    examples = [
        FewshotExample(
            id="fewshot_text1",
            sample_id="t1",
            input_text="text example",
            output_text='{"result": "dog"}',
            rationale_text="Focus on the decisive visual cue rather than superficial similarity.",
            rationale_source="fewshot_inline_generation",
            input_images=[],
        ),
    ]

    executor._execute_single(prompt, spec, examples)

    msgs = client.prepared_messages
    assert msgs is not None
    assert "Decision Rationale" in msgs[0]["content"]
    assert "decisive visual cue" in msgs[0]["content"]


def test_no_fewshot_uses_plain_system_message():
    """无 few-shot 时走默认 system message 路径。"""
    client = RecordingClient(base_url="https://example.test")
    executor = ExtractionExecutor(model_client=client)

    prompt = make_extraction_prompt()
    spec = make_spec("current_sample")

    executor._execute_single(prompt, spec, None)

    msgs = client.prepared_messages
    assert len(msgs) == 2
    assert "# Few-shot Examples" not in msgs[0]["content"]


# ---------------------------------------------------------------------------
# 3. _image_string_to_url 转换
# ---------------------------------------------------------------------------


def test_image_string_to_url_local_file_returns_data_url(tmp_path: Path):
    """本地文件路径 → base64 data URL。"""
    executor = ExtractionExecutor(model_client=RecordingClient(base_url="https://example.test"))
    img_bytes = b"\x89PNG\r\n\x1a\n" + b"fakepngdata"
    img_file = tmp_path / "test.png"
    img_file.write_bytes(img_bytes)

    url = executor._image_string_to_url(str(img_file), "owner1", 0)

    assert url is not None
    assert url.startswith("data:image/png;base64,")
    encoded = url.split(",", 1)[1]
    assert base64.b64decode(encoded) == img_bytes


def test_image_string_to_url_http_uri_returns_original():
    """HTTP URI → 原样返回。"""
    executor = ExtractionExecutor(model_client=RecordingClient(base_url="https://example.test"))
    uri = "https://example.test/image.jpg"

    url = executor._image_string_to_url(uri, "owner1", 0)

    assert url == uri


def test_image_string_to_url_local_file_passes_resize_config(tmp_path: Path, monkeypatch):
    executor = ExtractionExecutor(
        model_client=RecordingClient(base_url="https://example.test"),
        model_config={"image_resize": 0.5},
    )
    img_file = tmp_path / "test.png"
    img_file.write_bytes(b"placeholder")
    seen: dict[str, object] = {}

    def fake_encoder(local_path, mime_type=None, image_resize=None):
        seen["local_path"] = local_path
        seen["mime_type"] = mime_type
        seen["image_resize"] = image_resize
        return "data:image/png;base64,ZmFrZQ=="

    monkeypatch.setattr(
        "mmap_optimizer.executors.extraction_executor.encode_local_image_as_data_url",
        fake_encoder,
    )

    url = executor._image_string_to_url(str(img_file), "owner1", 0)

    assert url == "data:image/png;base64,ZmFrZQ=="
    assert seen["local_path"] == str(img_file)
    assert seen["mime_type"] == "image/png"
    assert seen["image_resize"] == 0.5


# ---------------------------------------------------------------------------
# 4. input_images 过滤
# ---------------------------------------------------------------------------


def test_select_difficult_samples_filters_non_image_and_empty_assets(tmp_path: Path):
    """``_select_difficult_samples`` 的 ``input_images`` 仅含非空图片资产。"""
    # 构造含混合资产的样本：1 张图片(uri)、1 张图片(local_path)、1 个非图片、1 个空图片
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
    metrics = FewshotMetrics()

    examples = phase._select_difficult_samples(batch, metrics)

    assert len(examples) == 1
    images = examples[0].input_images
    # 仅含 2 个非空图片资产，非图片资产和空资产被过滤
    assert len(images) == 2
    assert "https://example.test/a.png" in images
    assert str(tmp_path / "b.png") in images
    assert all(img for img in images)


def test_select_difficult_samples_no_image_assets_returns_empty_images(tmp_path: Path):
    """样本无图片资产时，``input_images`` 为空列表。"""
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


def test_fewshot_base_and_final_metrics_use_eval_status_for_state_and_trace(tmp_path: Path):
    """few-shot 结果的状态回填必须以评测结果为准，而不是解析结果。"""
    sample_set = SampleSet()
    sample_set.add_spec(
        SampleSpec(
            id="s1",
            input={"question": "what is shown?"},
            ground_truth={"result": "EXPECTED"},
            assets=[
                SampleAsset(id="img1", sample_id="s1", type="image", uri="https://example.test/s1-1.png"),
                SampleAsset(id="img2", sample_id="s1", type="image", uri="https://example.test/s1-2.png"),
            ],
        )
    )
    sample_set.states["s1"] = SampleState(sample_id="s1")
    sample_set.traces.append(
        SampleTrace(
            sample_id="s1",
            phase="fewshot_optimization",
            iteration=1,
            selected=True,
        )
    )

    phase = FewshotOptimizationPhase(
        config=FewshotConfig(slot_count=1, batch_size=1),
        extraction_prompt=make_extraction_prompt(),
        sample_set=sample_set,
        output_dir=tmp_path,
        fewshot_executor=FewshotExecutor(model_client=MockModelClient(default_output='{"result":"OK"}')),
    )
    phase.fewshot_examples = [
        FewshotExample(
            id="fewshot_ex1",
            sample_id="ex1",
            input_text="what is in the sample?",
            output_text='{"result":"cat"}',
            input_images=[
                "https://example.test/ex1-a.png",
                "https://example.test/ex1-b.png",
            ],
        )
    ]

    batch = SampleBatch(
        id="b1",
        phase="fewshot_optimization",
        iteration=1,
        sample_ids=["s1"],
        sampler_name="test",
    )

    base_results = phase._execute_extraction(batch)
    final_results = phase._execute_extraction_with_fewshot(batch, phase.fewshot_examples)
    assert base_results[0].status == "correct"
    assert final_results[0].status == "correct"

    metrics = FewshotMetrics()
    phase._compute_base_metrics(batch, base_results, metrics)
    phase._compute_final_metrics(batch, final_results, metrics)

    state = sample_set.states["s1"]
    trace = sample_set.get_traces_for_iteration("fewshot_optimization", 1)[0]

    assert metrics.base_correct_count == 0
    assert metrics.base_wrong_count == 1
    assert metrics.final_correct_count == 0
    assert metrics.final_wrong_count == 1
    assert state.error_count == 1
    assert state.last_extraction_status == "wrong"
    assert trace.base_extraction_result_id == "s1"
    assert trace.base_extraction_status == "wrong"
    assert trace.final_extraction_result_id == "s1"
    assert trace.final_extraction_status == "wrong"
