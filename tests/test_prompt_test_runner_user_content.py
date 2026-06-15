import json
from unittest import mock

from mmap_optimizer.dataset.sample import GroundTruth, Sample
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.testing.prompt_test_runner import PromptTestRunner


class RecordingModelClient:
    def __init__(self):
        self.call_args = []

    def complete_multimodal(self, messages, assets=None, model_config=None):
        self.call_args.append({
            "messages": [dict(m) for m in messages],
            "assets": assets
        })
        return mock.MagicMock(raw_output='{"result":"OK"}')


class MockEvaluator:
    def evaluate(self, **kwargs):
        return mock.MagicMock()

    def evaluate_without_ground_truth(self, **kwargs):
        return mock.MagicMock()


def make_mock_prompt(text: str = "system prompt") -> PromptVersion:
    mock_rendered = mock.MagicMock()
    mock_rendered.text = text
    mock_rendered.text_hash = "test-hash"
    
    prompt = mock.MagicMock(spec=PromptVersion)
    prompt.id = "test-prompt"
    prompt.render.return_value = mock_rendered
    return prompt


def test_prompt_test_runner_user_content_is_json_string():
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

    prompt = make_mock_prompt()
    sample = Sample(
        id="sample-1",
        ground_truth_id="gt-1",
        text_context="test context",
        structured_context={"key": "value"},
        metadata={"mock_output": "mock"},
    )
    ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer="test")

    runner.run(
        round_id="round-1",
        run_type="test",
        prompt=prompt,
        samples=[sample],
        assets={},
        ground_truths={"gt-1": ground_truth},
        contract=mock.MagicMock(),
    )

    assert len(model_client.call_args) == 1
    user_message = model_client.call_args[0]["messages"][1]
    assert user_message["role"] == "user"
    assert isinstance(user_message["content"], str)


def test_prompt_test_runner_user_content_json_parsable():
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

    prompt = make_mock_prompt()
    sample = Sample(
        id="sample-1",
        ground_truth_id="gt-1",
        text_context="test context",
        structured_context={"key": "value"},
        metadata={"mock_output": "mock"},
    )
    ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer="test")

    runner.run(
        round_id="round-1",
        run_type="test",
        prompt=prompt,
        samples=[sample],
        assets={},
        ground_truths={"gt-1": ground_truth},
        contract=mock.MagicMock(),
    )

    user_message = model_client.call_args[0]["messages"][1]
    content = json.loads(user_message["content"])
    assert "sample_id" in content
    assert "text_context" in content
    assert "structured_context" in content
    assert "mock_output" in content
    assert "mock_prompt_outputs" in content


def test_prompt_test_runner_user_content_fields():
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

    prompt = make_mock_prompt()
    sample = Sample(
        id="sample-1",
        ground_truth_id="gt-1",
        text_context="test context",
        structured_context={"nested": {"key": "value"}},
        metadata={"mock_output": "mock_response", "mock_prompt_outputs": ["output1", "output2"]},
    )
    ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer="test")

    runner.run(
        round_id="round-1",
        run_type="test",
        prompt=prompt,
        samples=[sample],
        assets={},
        ground_truths={"gt-1": ground_truth},
        contract=mock.MagicMock(),
    )

    user_message = model_client.call_args[0]["messages"][1]
    content = json.loads(user_message["content"])
    assert content["sample_id"] == "sample-1"
    assert content["text_context"] == "test context"
    assert content["structured_context"] == {"nested": {"key": "value"}}
    assert content["mock_output"] == "mock_response"
    assert content["mock_prompt_outputs"] == ["output1", "output2"]


def test_prompt_test_runner_user_content_chinese_not_escaped():
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

    prompt = make_mock_prompt()
    sample = Sample(
        id="sample-1",
        ground_truth_id="gt-1",
        text_context="中文内容测试",
        structured_context={"中文键": "中文值"},
        metadata={},
    )
    ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer="test")

    runner.run(
        round_id="round-1",
        run_type="test",
        prompt=prompt,
        samples=[sample],
        assets={},
        ground_truths={"gt-1": ground_truth},
        contract=mock.MagicMock(),
    )

    user_message = model_client.call_args[0]["messages"][1]
    content_str = user_message["content"]
    assert "中文内容测试" in content_str
    assert "中文键" in content_str
    assert "中文值" in content_str
    content = json.loads(content_str)
    assert content["text_context"] == "中文内容测试"
    assert content["structured_context"]["中文键"] == "中文值"


def test_prompt_test_runner_vote_mode_user_content_is_string():
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=3, enable_voting=True)

    prompt = make_mock_prompt()
    sample = Sample(
        id="sample-1",
        ground_truth_id="gt-1",
        text_context="test context",
        structured_context={},
        metadata={},
    )
    ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer=None)

    runner.run(
        round_id="round-1",
        run_type="test",
        prompt=prompt,
        samples=[sample],
        assets={},
        ground_truths={"gt-1": ground_truth},
        contract=mock.MagicMock(),
    )

    assert len(model_client.call_args) == 3
    for i, call in enumerate(model_client.call_args):
        user_message = call["messages"][1]
        assert isinstance(user_message["content"], str)
        content = json.loads(user_message["content"])
        assert content["vote_round"] == i + 1


def test_prompt_test_runner_vote_round_incremented():
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=3, enable_voting=True)

    prompt = make_mock_prompt()
    sample = Sample(
        id="sample-1",
        ground_truth_id="gt-1",
        text_context="test context",
        structured_context={},
        metadata={},
    )
    ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer=None)

    runner.run(
        round_id="round-1",
        run_type="test",
        prompt=prompt,
        samples=[sample],
        assets={},
        ground_truths={"gt-1": ground_truth},
        contract=mock.MagicMock(),
    )

    for i, call in enumerate(model_client.call_args):
        user_message = call["messages"][1]
        content = json.loads(user_message["content"])
        assert content["vote_round"] == i + 1
        assert content["sample_id"] == "sample-1"
        assert content["text_context"] == "test context"


def test_prompt_test_runner_no_vote_mode_with_ground_truth():
    model_client = RecordingModelClient()
    evaluator = MockEvaluator()
    runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=3, enable_voting=True)

    prompt = make_mock_prompt()
    sample = Sample(
        id="sample-1",
        ground_truth_id="gt-1",
        text_context="test context",
        structured_context={},
        metadata={},
    )
    ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer="test")

    runner.run(
        round_id="round-1",
        run_type="test",
        prompt=prompt,
        samples=[sample],
        assets={},
        ground_truths={"gt-1": ground_truth},
        contract=mock.MagicMock(),
    )

    assert len(model_client.call_args) == 1
    user_message = model_client.call_args[0]["messages"][1]
    content = json.loads(user_message["content"])
    assert "vote_round" not in content