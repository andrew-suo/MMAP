from __future__ import annotations

import json

from mmap_optimizer.data.dataset_loader import DatasetLoader, load_sample_specs
from mmap_optimizer.data.sample import (
    SampleAsset,
    SampleBatch,
    SampleSet,
    SampleSpec,
    SampleState,
)
from mmap_optimizer.data.sampler import SamplerConfig
from mmap_optimizer.executors.analysis_executor import AnalysisExecutor
from mmap_optimizer.executors.extraction_executor import ExtractionExecutor
from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.model.openai_compatible import OpenAICompatibleClient
from mmap_optimizer.phases.fewshot_optimization import (
    FewshotConfig,
    FewshotExample,
    FewshotMetrics,
    FewshotOptimizationPhase,
)
from mmap_optimizer.prompt.structured_prompt import PromptSection, StructuredPrompt


def test_load_sample_specs_preserves_multi_image_asset_order(tmp_path):
    dataset_path = tmp_path / "multi_image.jsonl"
    row = {
        "id": "s1",
        "input": {"text": "same sample"},
        "ground_truth": {"result": "NG"},
        "assets": [
            {"id": "a1", "type": "image", "local_path": "front.png", "mime_type": "image/png"},
            {"id": "a2", "type": "image", "local_path": "back.png", "mime_type": "image/png"},
            {"id": "a3", "type": "image", "local_path": "detail.png", "mime_type": "image/png"},
        ],
    }
    dataset_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    specs = load_sample_specs(dataset_path)

    assert len(specs) == 1
    assert [asset.id for asset in specs[0].assets] == ["a1", "a2", "a3"]
    assert [asset.local_path for asset in specs[0].assets] == [
        "front.png",
        "back.png",
        "detail.png",
    ]


def test_load_sample_specs_allows_text_only_samples_without_assets(tmp_path):
    dataset_path = tmp_path / "text_only.jsonl"
    row = {
        "id": "s1",
        "input": {"text": "text only"},
        "ground_truth": {"result": "OK"},
    }
    dataset_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    specs = load_sample_specs(dataset_path)

    assert len(specs) == 1
    assert specs[0].assets == []


def test_dataset_loader_applies_image_root_to_each_multi_image_asset(tmp_path):
    dataset_path = tmp_path / "multi_image.jsonl"
    image_root = tmp_path / "images"
    row = {
        "id": "s1",
        "input": {"text": "same sample"},
        "ground_truth": {"result": "OK"},
        "assets": [
            {"id": "a1", "type": "image", "local_path": "front.png", "mime_type": "image/png"},
            {"id": "a2", "type": "image", "local_path": "detail/detail.png", "mime_type": "image/png"},
        ],
    }
    dataset_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    sample_set = DatasetLoader(dataset_path=dataset_path, image_root=image_root).load()
    assets = sample_set.specs["s1"].assets

    assert [asset.local_path for asset in assets] == [
        str(image_root / "front.png"),
        str(image_root / "detail" / "detail.png"),
    ]


def test_sample_spec_round_trips_multi_image_assets_without_reordering():
    spec = SampleSpec(
        id="s1",
        input={"text": "same sample"},
        ground_truth={"result": "NG"},
        assets=[
            SampleAsset(id="a1", sample_id="s1", local_path="front.png", mime_type="image/png"),
            SampleAsset(id="a2", sample_id="s1", local_path="back.png", mime_type="image/png"),
        ],
    )

    restored = SampleSpec.from_dict(spec.to_dict())

    assert [asset.id for asset in restored.assets] == ["a1", "a2"]
    assert [asset.local_path for asset in restored.assets] == ["front.png", "back.png"]


def test_executors_build_all_multi_image_assets():
    spec = SampleSpec(
        id="s1",
        input={"text": "same sample"},
        ground_truth={"result": "OK"},
        assets=[
            SampleAsset(id="a1", sample_id="s1", uri="https://example.test/front.png", mime_type="image/png"),
            SampleAsset(id="a2", sample_id="s1", uri="https://example.test/back.png", mime_type="image/png"),
            SampleAsset(id="a3", sample_id="s1", type="text", uri="https://example.test/note.txt"),
        ],
    )

    extraction_assets = ExtractionExecutor(MockModelClient())._build_assets(spec)
    analysis_assets = AnalysisExecutor(model_client=None)._build_assets(spec)

    assert [asset.id for asset in extraction_assets] == ["a1", "a2"]
    assert [asset.id for asset in analysis_assets] == ["a1", "a2"]


def test_extraction_user_message_does_not_include_metadata_category():
    spec = SampleSpec(
        id="s1",
        input={"text": "inspect the sample"},
        ground_truth={"result": "OK"},
        metadata={"category": "correct", "difficulty": "easy"},
    )

    message = ExtractionExecutor(MockModelClient())._build_user_message(spec)

    assert message["role"] == "user"
    assert "Sample Input:" in message["content"]
    assert "Metadata:" not in message["content"]
    assert "category" not in message["content"]
    assert "correct" not in message["content"]


def test_analysis_blind_message_does_not_include_metadata_category():
    prompt = StructuredPrompt(
        id="p1",
        prompt_type="analysis",
        sections=[
            PromptSection(
                id="section_1",
                title="Task",
                level=1,
                content="Judge the extraction result from the evidence only.",
                mutable=True,
            )
        ],
        raw_markdown="# Task\nJudge the extraction result from the evidence only.",
    )
    extraction_prompt = StructuredPrompt(
        id="ext1",
        prompt_type="extraction",
        sections=[
            PromptSection(
                id="section_1",
                title="Task",
                level=1,
                content="Extract a sample-level result.",
                mutable=True,
            )
        ],
        raw_markdown="# Task\nExtract a sample-level result.",
    )
    extraction_result = type(
        "_ExtractionResult",
        (),
        {
            "sample_id": "s1",
            "status": "correct",
            "evaluation_status": "wrong",
            "raw_output": '{"result":"OK"}',
            "parsed_output": {"result": "OK"},
            "error_details": [],
        },
    )()
    sample_spec = SampleSpec(
        id="s1",
        input={"text": "inspect the sample"},
        ground_truth={"result": "NG"},
        metadata={"category": "error", "difficulty": "medium"},
    )

    messages, _ = AnalysisExecutor(model_client=MockModelClient())._build_analysis_messages(
        prompt,
        extraction_prompt,
        extraction_result,
        sample_spec,
    )

    user_content = messages[1]["content"]
    assert "# Sample Input" in user_content
    assert "# Sample Metadata" not in user_content
    assert "category" not in user_content
    assert "error" not in user_content


def test_openai_compatible_client_keeps_multiple_images_for_one_sample():
    client = OpenAICompatibleClient(base_url="https://example.test")
    assets = [
        SampleAsset(id="a1", sample_id="s1", uri="https://example.test/front.png", mime_type="image/png"),
        SampleAsset(id="a2", sample_id="s1", uri="https://example.test/back.png", mime_type="image/png"),
    ]

    messages = client._messages_with_assets(
        [{"role": "user", "content": "analyze the sample"}],
        assets,
    )

    user_parts = messages[0]["content"]
    assert len(user_parts) == 3
    assert user_parts[1]["image_url"]["url"] == "https://example.test/front.png"
    assert user_parts[2]["image_url"]["url"] == "https://example.test/back.png"


def test_render_with_fewshot_lists_all_images_for_same_sample():
    prompt = StructuredPrompt(
        id="p1",
        prompt_type="extraction",
        sections=[
            PromptSection(
                id="section_1",
                title="Task",
                level=1,
                content="Judge the provided image(s) together and return one sample-level result.",
                mutable=True,
            )
        ],
        raw_markdown="# Task\n\nJudge the provided image(s) together and return one sample-level result.",
    )
    example = FewshotExample(
        id="fewshot_s1",
        sample_id="s1",
        input_text="same product, multiple views",
        input_images=["front.png", "back.png", "detail.png"],
        output_text='{"result":"NG"}',
        output_data={"result": "NG"},
        rationale_text="Consider all images together before deciding the sample-level result.",
        rationale_source="fewshot_inline_generation",
    )

    rendered = prompt.render_with_fewshot([example])

    assert "Input Images:" in rendered
    assert "same sample and should be considered together" in rendered
    assert "- front.png" in rendered
    assert "- back.png" in rendered
    assert "- detail.png" in rendered
    assert "Decision Rationale:" in rendered
    assert "Consider all images together" in rendered


def test_fewshot_selection_carries_all_sample_images(tmp_path):
    spec = SampleSpec(
        id="s1",
        input={"text": "same product, multiple views"},
        ground_truth={"result": "NG"},
        assets=[
            SampleAsset(id="a1", sample_id="s1", local_path="front.png", mime_type="image/png"),
            SampleAsset(id="a2", sample_id="s1", local_path="detail.png", mime_type="image/png"),
        ],
    )
    sample_set = SampleSet(
        specs={"s1": spec},
        states={"s1": SampleState(sample_id="s1", difficulty_score=1.0)},
    )

    phase = FewshotOptimizationPhase(
        config=FewshotConfig(
            enabled=True,
            rounds=1,
            batch_size=1,
            slot_count=1,
            sampler=SamplerConfig(type="frequency"),
        ),
        extraction_prompt=StructuredPrompt(
            id="p1",
            prompt_type="extraction",
            sections=[],
            raw_markdown="",
        ),
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
    assert examples[0].input_images == ["front.png", "detail.png"]
