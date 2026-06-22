"""Tests for few-shot multi-turn message construction in PromptTestRunner."""

import json
from unittest import mock

from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.ir import PromptIR, PromptSection
from mmap_optimizer.prompt.renderer import PromptRenderer
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.testing.prompt_test_runner import (
    PromptTestRunner,
    _parse_fewshot_slots,
    _build_fewshot_messages,
    _render_system_without_fewshot,
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
    """Create a real PromptVersion with optional sections."""
    prompt_ir = PromptIR(
        id="test_ir",
        prompt_type=PromptType.EXTRACTION,
        version=1,
        output_schema_contract_id="test_contract",
        sections=sections or [],
        rendering_order=[s.id for s in (sections or [])],
    )
    prompt = PromptVersion(
        id="test-prompt",
        prompt_type=PromptType.EXTRACTION,
        version=1,
        prompt_ir=prompt_ir,
        output_schema_contract_id="test_contract",
    )
    prompt.render()
    return prompt


def test_parse_fewshot_slots_empty():
    """Empty content returns empty list."""
    assert _parse_fewshot_slots("") == []


def test_parse_fewshot_slots_single():
    """Parse a single slot with reasoning and output."""
    content = """FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:fs_sample_1
FEW_SHOT_REASONING:
example reasoning
FEW_SHOT_OUTPUT:
{"result": "OK"}"""
    slots = _parse_fewshot_slots(content)
    assert len(slots) == 1
    assert slots[0]["slot_index"] == 1
    assert slots[0]["source_sample_id"] == "fs_sample_1"
    assert slots[0]["reasoning_text"] == "example reasoning"
    assert slots[0]["final_output"] == '{"result": "OK"}'


def test_parse_fewshot_slots_multiple():
    """Parse multiple slots."""
    content = """FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:fs_sample_1
FEW_SHOT_REASONING:
reasoning 1
FEW_SHOT_OUTPUT:
{"a": 1}

FEW_SHOT_SLOT:2
FEW_SHOT_SAMPLE:fs_sample_2
FEW_SHOT_REASONING:
reasoning 2
FEW_SHOT_OUTPUT:
{"b": 2}"""
    slots = _parse_fewshot_slots(content)
    assert len(slots) == 2
    assert slots[0]["slot_index"] == 1
    assert slots[0]["source_sample_id"] == "fs_sample_1"
    assert slots[1]["slot_index"] == 2
    assert slots[1]["source_sample_id"] == "fs_sample_2"


def test_build_fewshot_messages_structure():
    """Build multi-turn messages from slots."""
    slots = [
        {"slot_index": 1, "source_sample_id": "fs_sample_1", "reasoning_text": "reasoning", "final_output": '{"result":"OK"}'},
    ]
    samples = [
        Sample(id="fs_sample_1", ground_truth_id="gt1", asset_ids=["fs_asset"]),
    ]
    assets = {
        "fs_asset": SampleAsset(id="fs_asset", sample_id="fs_sample_1", uri="https://example.com/fs.png", mime_type="image/png"),
    }

    messages = _build_fewshot_messages(slots, samples, assets)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == '{"result": "OK"}'

    # User message should have content parts (text + image)
    content = messages[0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert "reasoning" in content[0]["text"]
    assert "FEW_SHOT_SAMPLE:fs_sample_1" in content[0]["text"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "https://example.com/fs.png"


def test_build_fewshot_messages_missing_sample():
    """Missing sample still produces messages without images."""
    slots = [
        {"slot_index": 1, "source_sample_id": "missing", "reasoning_text": "reasoning", "final_output": '{"result":"OK"}'},
    ]
    samples = []
    assets = {}

    messages = _build_fewshot_messages(slots, samples, assets)
    assert len(messages) == 2
    content = messages[0]["content"]
    assert isinstance(content, list)
    assert len(content) == 1  # Only text part, no image
    assert content[0]["type"] == "text"


def test_render_system_without_fewshot():
    """System text excludes few-shot section content."""
    fewshot_section = PromptSection(
        id=FEWSHOT_SECTION_ID,
        type="few_shot_examples",
        content="FEW_SHOT_SLOT:1\nFEW_SHOT_SAMPLE:s1\nFEW_SHOT_REASONING:\nr\nFEW_SHOT_OUTPUT:\n{}",
        name="Few-shot examples",
    )
    main_section = PromptSection(
        id="main",
        type="instructions",
        content="You are an extraction assistant.",
        name="Main",
    )
    prompt = make_mock_prompt(sections=[main_section, fewshot_section])

    system_text = _render_system_without_fewshot(prompt)
    assert "extraction assistant" in system_text
    assert "FEW_SHOT_SLOT" not in system_text


def test_prompt_test_runner_multiturn_messages():
    """Few-shot produces multi-turn messages with user/assistant pairs."""
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

    fewshot_section = PromptSection(
        id=FEWSHOT_SECTION_ID,
        type="few_shot_examples",
        content="""FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:fs_sample_1
FEW_SHOT_REASONING:
example reasoning
FEW_SHOT_OUTPUT:
{"result": "OK"}""",
        name="Few-shot examples",
    )
    main_section = PromptSection(
        id="main",
        type="instructions",
        content="You are an extraction assistant.",
        name="Main",
    )
    prompt = make_mock_prompt(sections=[main_section, fewshot_section])

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
        samples=samples,
        assets=assets,
        ground_truths=ground_truths,
        contract=mock.MagicMock(spec=OutputSchemaContract),
    )

    # 2 samples = 2 calls
    assert len(model_client.call_args) == 2

    # Each call should have multi-turn messages: system + user + assistant + user
    for call in model_client.call_args:
        messages = call["messages"]
        assert messages[0]["role"] == "system"
        # Few-shot user/assistant pair
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"
        assert messages[2]["content"] == '{"result": "OK"}'
        # Current sample user message
        assert messages[3]["role"] == "user"

    # Only sample assets passed to complete_multimodal (not fewshot assets)
    test_sample_call = model_client.call_args[1]  # test_sample is second
    assert test_sample_call["assets"] == ["test_asset"]


def test_prompt_test_runner_no_fewshot_single_turn():
    """Without few-shot, messages are single-turn (system + user)."""
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

    prompt = make_mock_prompt()

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
    messages = model_client.call_args[0]["messages"]
    assert len(messages) == 2  # system + user only
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_prompt_test_runner_missing_fewshot_sample_no_images():
    """Missing few-shot sample produces user message without images."""
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

    fewshot_section = PromptSection(
        id=FEWSHOT_SECTION_ID,
        type="few_shot_examples",
        content="""FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:missing_sample
FEW_SHOT_REASONING:
reasoning
FEW_SHOT_OUTPUT:
{"result": "OK"}""",
        name="Few-shot examples",
    )
    main_section = PromptSection(
        id="main",
        type="instructions",
        content="You are an extraction assistant.",
        name="Main",
    )
    prompt = make_mock_prompt(sections=[main_section, fewshot_section])

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
    messages = model_client.call_args[0]["messages"]
    # system + user(fewshot, no images) + assistant + user(sample)
    assert len(messages) == 4
    # Few-shot user message should have only text part (no image)
    fewshot_user_content = messages[1]["content"]
    assert isinstance(fewshot_user_content, list)
    assert all(part["type"] == "text" for part in fewshot_user_content)


def test_prompt_test_runner_no_images_still_works():
    """Test without any images still works correctly."""
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

    fewshot_section = PromptSection(
        id=FEWSHOT_SECTION_ID,
        type="few_shot_examples",
        content="""FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:fs_sample_1
FEW_SHOT_REASONING:
reasoning
FEW_SHOT_OUTPUT:
{"result": "OK"}""",
        name="Few-shot examples",
    )
    main_section = PromptSection(
        id="main",
        type="instructions",
        content="You are an extraction assistant.",
        name="Main",
    )
    prompt = make_mock_prompt(sections=[main_section, fewshot_section])

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
    """Evaluator is still called correctly with few-shot multi-turn messages."""
    evaluator = MockEvaluator()
    mock_evaluate = mock.patch.object(evaluator, "evaluate", return_value=mock.MagicMock())
    with mock_evaluate as mock_eval:
        model_client = RecordingModelClient()
        runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

        fewshot_section = PromptSection(
            id=FEWSHOT_SECTION_ID,
            type="few_shot_examples",
            content="""FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:fs_sample_1
FEW_SHOT_REASONING:
reasoning
FEW_SHOT_OUTPUT:
{"result": "OK"}""",
            name="Few-shot examples",
        )
        main_section = PromptSection(
            id="main",
            type="instructions",
            content="You are an extraction assistant.",
            name="Main",
        )
        prompt = make_mock_prompt(sections=[main_section, fewshot_section])

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
            samples=samples,
            assets=assets,
            ground_truths=ground_truths,
            contract=mock.MagicMock(spec=OutputSchemaContract),
        )

        assert mock_eval.called
        assert len(result.evaluations) == 2  # 2 samples
