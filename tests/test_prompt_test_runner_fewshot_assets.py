"""Tests for few-shot asset delivery in PromptTestRunner."""

import json
from unittest import mock

from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.ir import PromptIR, PromptSection
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.testing.prompt_test_runner import (
    PromptTestRunner,
    _extract_fewshot_asset_ids,
    FEWSHOT_SECTION_ID,
)


class RecordingModelClient:
    """Test model client that records calls."""

    def __init__(self):
        self.call_args = []

    def complete_multimodal(self, messages, assets=None, model_config=None):
        self.call_args.append({
            "messages": messages,
            "assets": [a.id for a in (assets or [])],
        })
        return mock.MagicMock(raw_output='{"result":"OK"}')


class MockEvaluator:
    def evaluate(self, **kwargs):
        return mock.MagicMock()

    def evaluate_without_ground_truth(self, **kwargs):
        return mock.MagicMock()


def make_mock_prompt(sections=None) -> PromptVersion:
    """Create a mock prompt with optional sections."""
    prompt_ir = PromptIR(
        id="test_ir",
        prompt_type=PromptType.EXTRACTION,
        version=1,
        output_schema_contract_id="test_contract",
        sections=sections or [],
    )
    prompt = mock.MagicMock(spec=PromptVersion)
    prompt.id = "test-prompt"
    prompt.prompt_ir = prompt_ir
    mock_rendered = mock.MagicMock()
    mock_rendered.text = "system prompt"
    mock_rendered.text_hash = "test-hash"
    prompt.render.return_value = mock_rendered
    return prompt


def test_extract_fewshot_asset_ids_empty_prompt():
    """Empty prompt returns empty list."""
    prompt = make_mock_prompt()
    samples = []
    asset_ids = _extract_fewshot_asset_ids(prompt, samples)
    assert asset_ids == []


def test_extract_fewshot_asset_ids_from_section_content():
    """Asset IDs are extracted from FEW_SHOT_SAMPLE lines in section content."""
    fewshot_section = PromptSection(
        id=FEWSHOT_SECTION_ID,
        type="few_shot_examples",
        content="""FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:fs_sample_1
分析过程示例:
example reasoning
最终输出示例:
{"result": "OK"}""",
        name="Few-shot examples",
    )
    prompt = make_mock_prompt(sections=[fewshot_section])

    samples = [
        Sample(id="fs_sample_1", ground_truth_id="gt1", asset_ids=["fs_asset_1", "fs_asset_2"]),
        Sample(id="test_sample", ground_truth_id="gt2", asset_ids=["test_asset"]),
    ]

    asset_ids = _extract_fewshot_asset_ids(prompt, samples)
    assert asset_ids == ["fs_asset_1", "fs_asset_2"]


def test_extract_fewshot_asset_ids_from_section_constraints():
    """Asset IDs are extracted from section constraints."""
    fewshot_section = PromptSection(
        id=FEWSHOT_SECTION_ID,
        type="few_shot_examples",
        content="FEW_SHOT_SLOT:1\nFEW_SHOT_SAMPLE:fs_sample_1",
        name="Few-shot examples",
        constraints={"fewshot_asset_ids": ["fs_asset_1", "fs_asset_2"]},
    )
    prompt = make_mock_prompt(sections=[fewshot_section])

    samples = [
        Sample(id="fs_sample_1", ground_truth_id="gt1", asset_ids=["fs_asset_1", "fs_asset_2"]),
    ]

    asset_ids = _extract_fewshot_asset_ids(prompt, samples)
    assert "fs_asset_1" in asset_ids
    assert "fs_asset_2" in asset_ids


def test_extract_fewshot_asset_ids_deduplicated():
    """Duplicate asset IDs are removed."""
    fewshot_section = PromptSection(
        id=FEWSHOT_SECTION_ID,
        type="few_shot_examples",
        content="""FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:fs_sample_1
FEW_SHOT_SAMPLE:fs_sample_2""",
        name="Few-shot examples",
    )
    prompt = make_mock_prompt(sections=[fewshot_section])

    samples = [
        Sample(id="fs_sample_1", ground_truth_id="gt1", asset_ids=["shared_asset", "asset_1"]),
        Sample(id="fs_sample_2", ground_truth_id="gt1", asset_ids=["shared_asset", "asset_2"]),
    ]

    asset_ids = _extract_fewshot_asset_ids(prompt, samples)
    assert asset_ids.count("shared_asset") == 1
    assert len(asset_ids) == 3


def test_extract_fewshot_asset_ids_missing_sample_skipped():
    """Missing sample IDs are skipped without error."""
    fewshot_section = PromptSection(
        id=FEWSHOT_SECTION_ID,
        type="few_shot_examples",
        content="""FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:missing_sample
FEW_SHOT_SAMPLE:existing_sample""",
        name="Few-shot examples",
    )
    prompt = make_mock_prompt(sections=[fewshot_section])

    samples = [
        Sample(id="existing_sample", ground_truth_id="gt1", asset_ids=["existing_asset"]),
    ]

    asset_ids = _extract_fewshot_asset_ids(prompt, samples)
    assert asset_ids == ["existing_asset"]


def test_extract_fewshot_asset_ids_order_preserved():
    """Asset IDs order is preserved (few-shot before sample)."""
    fewshot_section = PromptSection(
        id=FEWSHOT_SECTION_ID,
        type="few_shot_examples",
        content="""FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:first_sample
FEW_SHOT_SLOT:2
FEW_SHOT_SAMPLE:second_sample""",
        name="Few-shot examples",
    )
    prompt = make_mock_prompt(sections=[fewshot_section])

    samples = [
        Sample(id="first_sample", ground_truth_id="gt1", asset_ids=["first_asset"]),
        Sample(id="second_sample", ground_truth_id="gt1", asset_ids=["second_asset"]),
    ]

    asset_ids = _extract_fewshot_asset_ids(prompt, samples)
    assert asset_ids == ["first_asset", "second_asset"]


def test_prompt_test_runner_sends_fewshot_images_first():
    """Few-shot images are sent before sample images."""
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

    fewshot_section = PromptSection(
        id=FEWSHOT_SECTION_ID,
        type="few_shot_examples",
        content="""FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:fs_sample_1""",
        name="Few-shot examples",
    )
    prompt = make_mock_prompt(sections=[fewshot_section])

    samples = [
        Sample(id="fs_sample_1", ground_truth_id="gt_fs", asset_ids=["fs_asset"]),
        Sample(id="test_sample", ground_truth_id="gt1", asset_ids=["test_asset"]),
    ]
    assets = {
        "fs_asset": SampleAsset(id="fs_asset", sample_id="fs_sample_1", uri="https://example.com/fs.png", mime_type="image/png"),
        "test_asset": SampleAsset(id="test_asset", sample_id="test_sample", uri="https://example.com/test.png", mime_type="image/png"),
    }
    ground_truths = {"gt1": GroundTruth(id="gt1", sample_id="test_sample", value={"result": "OK"}, primary_answer="OK")}

    runner.run(
        round_id="round-1",
        run_type="test",
        prompt=prompt,
        samples=samples,  # Include fs_sample_1 for few-shot lookup
        assets=assets,
        ground_truths=ground_truths,
        contract=mock.MagicMock(spec=OutputSchemaContract),
    )

    assert len(model_client.call_args) == 2
    first_call_assets = model_client.call_args[0]["assets"]
    second_call_assets = model_client.call_args[1]["assets"]
    # test_sample is second, but fs_asset should come before test_asset
    assert second_call_assets[0] == "fs_asset"
    assert second_call_assets[1] == "test_asset"


def test_prompt_test_runner_no_fewshot_only_sample_images():
    """Without few-shot, only sample images are sent."""
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

    prompt = make_mock_prompt()

    samples = [Sample(id="test_sample", ground_truth_id="gt1", asset_ids=["test_asset"])]
    assets = {
        "test_asset": SampleAsset(id="test_asset", sample_id="test_sample", local_path="/tmp/test.png", mime_type="image/png"),
    }
    ground_truths = {"gt1": GroundTruth(id="gt1", sample_id="test_sample", value={"result": "OK"}, primary_answer="OK")}

    runner.run(
        round_id="round-1",
        run_type="test",
        prompt=prompt,
        samples=samples,
        assets=assets,
        ground_truths=ground_truths,
        contract=mock.MagicMock(spec=OutputSchemaContract),
    )

    assert len(model_client.call_args) == 1
    asset_ids = model_client.call_args[0]["assets"]
    assert asset_ids == ["test_asset"]


def test_prompt_test_runner_missing_fewshot_asset_skipped():
    """Missing few-shot assets are skipped without error."""
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

    fewshot_section = PromptSection(
        id=FEWSHOT_SECTION_ID,
        type="few_shot_examples",
        content="""FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:missing_sample""",
        name="Few-shot examples",
    )
    prompt = make_mock_prompt(sections=[fewshot_section])

    samples = [Sample(id="test_sample", ground_truth_id="gt1", asset_ids=["test_asset"])]
    assets = {
        "test_asset": SampleAsset(id="test_asset", sample_id="test_sample", uri="https://example.com/test.png", mime_type="image/png"),
    }
    ground_truths = {"gt1": GroundTruth(id="gt1", sample_id="test_sample", value={"result": "OK"}, primary_answer="OK")}

    runner.run(
        round_id="round-1",
        run_type="test",
        prompt=prompt,
        samples=samples,
        assets=assets,
        ground_truths=ground_truths,
        contract=mock.MagicMock(spec=OutputSchemaContract),
    )

    assert len(model_client.call_args) == 1
    asset_ids = model_client.call_args[0]["assets"]
    assert asset_ids == ["test_asset"]


def test_prompt_test_runner_no_images_still_works():
    """Test without any images still works correctly."""
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

    fewshot_section = PromptSection(
        id=FEWSHOT_SECTION_ID,
        type="few_shot_examples",
        content="""FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:fs_sample_1""",
        name="Few-shot examples",
    )
    prompt = make_mock_prompt(sections=[fewshot_section])

    samples = [Sample(id="test_sample", ground_truth_id="gt1", asset_ids=[])]
    assets = {}
    ground_truths = {"gt1": GroundTruth(id="gt1", sample_id="test_sample", value={"result": "OK"}, primary_answer="OK")}

    runner.run(
        round_id="round-1",
        run_type="test",
        prompt=prompt,
        samples=samples,
        assets=assets,
        ground_truths=ground_truths,
        contract=mock.MagicMock(spec=OutputSchemaContract),
    )

    assert len(model_client.call_args) == 1
    assert model_client.call_args[0]["assets"] == []


def test_prompt_test_runner_evaluator_still_called():
    """Evaluator is still called correctly with few-shot images."""
    evaluator = MockEvaluator()
    mock_evaluate = mock.patch.object(evaluator, "evaluate", return_value=mock.MagicMock())
    with mock_evaluate as mock_eval:
        model_client = RecordingModelClient()
        runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

        fewshot_section = PromptSection(
            id=FEWSHOT_SECTION_ID,
            type="few_shot_examples",
            content="FEW_SHOT_SLOT:1\nFEW_SHOT_SAMPLE:fs_sample_1",
            name="Few-shot examples",
        )
        prompt = make_mock_prompt(sections=[fewshot_section])

        samples = [
            Sample(id="fs_sample_1", ground_truth_id="gt_fs", asset_ids=["fs_asset"]),
            Sample(id="test_sample", ground_truth_id="gt1", asset_ids=["test_asset"]),
        ]
        assets = {
            "fs_asset": SampleAsset(id="fs_asset", sample_id="fs_sample_1", uri="https://example.com/fs.png", mime_type="image/png"),
            "test_asset": SampleAsset(id="test_asset", sample_id="test_sample", uri="https://example.com/test.png", mime_type="image/png"),
        }
        ground_truths = {"gt1": GroundTruth(id="gt1", sample_id="test_sample", value={"result": "OK"}, primary_answer="OK")}

        result = runner.run(
            round_id="round-1",
            run_type="test",
            prompt=prompt,
            samples=samples,  # Include fs_sample_1 for few-shot lookup
            assets=assets,
            ground_truths=ground_truths,
            contract=mock.MagicMock(spec=OutputSchemaContract),
        )

        assert mock_eval.called
        assert len(result.evaluations) == 2  # 2 samples (fs_sample_1 and test_sample)
