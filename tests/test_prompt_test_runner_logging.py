"""Tests for PromptTestRunner runtime logging."""

import logging
from unittest import mock

import pytest

from mmap_optimizer.dataset.sample import GroundTruth, Sample
from mmap_optimizer.evaluation.evaluator import EvaluationRecord
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.testing.prompt_test_runner import PromptTestRunner


class RecordingModelClient:
    """Test model client that records calls."""

    def __init__(self):
        self.call_args = []
        self.response_count = 0

    def complete_multimodal(self, messages, assets=None, model_config=None):
        self.call_args.append({
            "messages": [dict(m) for m in messages],
            "assets": assets,
            "model_config": model_config,
        })
        self.response_count += 1
        return mock.MagicMock(raw_output='{"result":"OK"}')


class MockEvaluator:
    """Test evaluator."""

    def evaluate(self, **kwargs):
        return EvaluationRecord(
            id=f"eval-{kwargs.get('sample_id', 'sample-1')}",
            round_id=kwargs.get("round_id", "round-1"),
            run_id=kwargs.get("run_id", "run-1"),
            sample_id=kwargs.get("sample_id", "sample-1"),
            ground_truth_id=kwargs.get("ground_truth", mock.MagicMock()).id if kwargs.get("ground_truth") else "gt-1",
            parse_success=True,
            schema_valid=True,
            primary_answer_correct=True,
            overall_status="correct",
        )

    def evaluate_without_ground_truth(self, **kwargs):
        return EvaluationRecord(
            id=f"eval-{kwargs.get('sample_id', 'sample-1')}",
            round_id=kwargs.get("round_id", "round-1"),
            run_id=kwargs.get("run_id", "run-1"),
            sample_id=kwargs.get("sample_id", "sample-1"),
            ground_truth_id="gt-unknown",
            parse_success=True,
            schema_valid=True,
            primary_answer_correct=True,
            overall_status="correct",
        )


def make_mock_prompt(text: str = "system prompt") -> PromptVersion:
    """Create a mock prompt for testing."""
    mock_rendered = mock.MagicMock()
    mock_rendered.text = text
    mock_rendered.text_hash = "test-hash"

    prompt = mock.MagicMock(spec=PromptVersion)
    prompt.id = "test-prompt"
    prompt.render.return_value = mock_rendered
    return prompt


class TestPromptTestRunnerLogging:
    """Tests for PromptTestRunner logging."""

    def test_sample_start_logged(self, caplog):
        """sample_start should be logged when processing begins."""
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

        with caplog.at_level(logging.INFO):
            runner.run(
                round_id="round-1",
                run_type="test",
                prompt=prompt,
                samples=[sample],
                assets={},
                ground_truths={"gt-1": ground_truth},
                contract=mock.MagicMock(),
            )
        assert "sample_start" in caplog.text
        assert "sample_id=sample-1" in caplog.text

    def test_sample_done_logged(self, caplog):
        """sample_done should be logged when processing completes."""
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

        with caplog.at_level(logging.INFO):
            runner.run(
                round_id="round-1",
                run_type="test",
                prompt=prompt,
                samples=[sample],
                assets={},
                ground_truths={"gt-1": ground_truth},
                contract=mock.MagicMock(),
            )
        assert "sample_done" in caplog.text
        assert "sample_id=sample-1" in caplog.text
        assert "decision=correct" in caplog.text

    def test_model_call_start_logged(self, caplog):
        """model_call_start should be logged before model call."""
        model_client = RecordingModelClient()
        evaluator = MockEvaluator()
        runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

        prompt = make_mock_prompt()
        sample = Sample(
            id="sample-1",
            ground_truth_id="gt-1",
            text_context="test context",
            structured_context={},
            metadata={},
        )
        ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer="test")

        with caplog.at_level(logging.INFO):
            runner.run(
                round_id="round-1",
                run_type="test",
                prompt=prompt,
                samples=[sample],
                assets={},
                ground_truths={"gt-1": ground_truth},
                contract=mock.MagicMock(),
            )
        assert "model_call_start" in caplog.text
        assert "vote_index=0" in caplog.text

    def test_model_call_done_logged(self, caplog):
        """model_call_done should be logged after model call."""
        model_client = RecordingModelClient()
        evaluator = MockEvaluator()
        runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

        prompt = make_mock_prompt()
        sample = Sample(
            id="sample-1",
            ground_truth_id="gt-1",
            text_context="test context",
            structured_context={},
            metadata={},
        )
        ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer="test")

        with caplog.at_level(logging.INFO):
            runner.run(
                round_id="round-1",
                run_type="test",
                prompt=prompt,
                samples=[sample],
                assets={},
                ground_truths={"gt-1": ground_truth},
                contract=mock.MagicMock(),
            )
        assert "model_call_done" in caplog.text
        assert "duration_ms=" in caplog.text
        assert "response_chars=" in caplog.text

    def test_parse_done_logged(self, caplog):
        """parse_done should be logged after JSON parsing."""
        model_client = RecordingModelClient()
        evaluator = MockEvaluator()
        runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

        prompt = make_mock_prompt()
        sample = Sample(
            id="sample-1",
            ground_truth_id="gt-1",
            text_context="test context",
            structured_context={},
            metadata={},
        )
        ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer="test")

        with caplog.at_level(logging.INFO):
            runner.run(
                round_id="round-1",
                run_type="test",
                prompt=prompt,
                samples=[sample],
                assets={},
                ground_truths={"gt-1": ground_truth},
                contract=mock.MagicMock(),
            )
        assert "parse_done" in caplog.text
        assert "status=ok" in caplog.text

    def test_evaluate_done_logged(self, caplog):
        """evaluate_done should be logged after evaluation."""
        model_client = RecordingModelClient()
        evaluator = MockEvaluator()
        runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

        prompt = make_mock_prompt()
        sample = Sample(
            id="sample-1",
            ground_truth_id="gt-1",
            text_context="test context",
            structured_context={},
            metadata={},
        )
        ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer="test")

        with caplog.at_level(logging.INFO):
            runner.run(
                round_id="round-1",
                run_type="test",
                prompt=prompt,
                samples=[sample],
                assets={},
                ground_truths={"gt-1": ground_truth},
                contract=mock.MagicMock(),
            )
        assert "evaluate_done" in caplog.text
        assert "decision=correct" in caplog.text


class TestPromptTestRunnerErrorLogging:
    """Tests for PromptTestRunner error logging."""

    def test_sample_failed_on_exception(self, caplog):
        """sample_failed should be logged when exception occurs."""

        class FailingModelClient:
            def complete_multimodal(self, messages, assets=None, model_config=None):
                raise RuntimeError("Model error")

        model_client = FailingModelClient()
        evaluator = MockEvaluator()
        runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

        prompt = make_mock_prompt()
        sample = Sample(
            id="sample-1",
            ground_truth_id="gt-1",
            text_context="test context",
            structured_context={},
            metadata={},
        )
        ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer="test")

        with caplog.at_level(logging.INFO):
            result = runner.run(
                round_id="round-1",
                run_type="test",
                prompt=prompt,
                samples=[sample],
                assets={},
                ground_truths={"gt-1": ground_truth},
                contract=mock.MagicMock(),
            )
        assert "sample_failed" in caplog.text
        assert "sample_id=sample-1" in caplog.text
        assert "RuntimeError" in caplog.text
        # Error is now returned as a failed record, not raised
        assert len(result.runs) == 1
        assert len(result.evaluations) == 1
        assert result.evaluations[0].overall_status == "ERROR"

    def test_parse_failed_logs_warning(self, caplog):
        """parse_failed should log a warning."""

        class BadJsonModelClient:
            def complete_multimodal(self, messages, assets=None, model_config=None):
                return mock.MagicMock(raw_output="not valid json")

        model_client = BadJsonModelClient()
        evaluator = MockEvaluator()
        runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

        prompt = make_mock_prompt()
        sample = Sample(
            id="sample-1",
            ground_truth_id="gt-1",
            text_context="test context",
            structured_context={},
            metadata={},
        )
        ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer="test")

        with caplog.at_level(logging.INFO):
            runner.run(
                round_id="round-1",
                run_type="test",
                prompt=prompt,
                samples=[sample],
                assets={},
                ground_truths={"gt-1": ground_truth},
                contract=mock.MagicMock(),
            )
        assert "parse_done" in caplog.text
        assert "status=failed" in caplog.text


class TestPromptTestRunnerLoggingWithAssets:
    """Tests for PromptTestRunner logging with assets."""

    def test_asset_count_in_logs(self, caplog):
        """asset_count should be logged in sample_start."""
        model_client = RecordingModelClient()
        evaluator = MockEvaluator()
        runner = PromptTestRunner(model_client=model_client, evaluator=evaluator, vote_rounds=1, enable_voting=False)

        prompt = make_mock_prompt()
        sample = Sample(
            id="sample-1",
            ground_truth_id="gt-1",
            text_context="test context",
            structured_context={},
            asset_ids=["asset-1"],
            metadata={},
        )
        ground_truth = GroundTruth(id="gt-1", sample_id="sample-1", value={"answer": "test"}, primary_answer="test")

        mock_asset = mock.MagicMock()
        mock_asset.id = "asset-1"
        mock_asset.type = "image"

        with caplog.at_level(logging.INFO):
            runner.run(
                round_id="round-1",
                run_type="test",
                prompt=prompt,
                samples=[sample],
                assets={"asset-1": mock_asset},
                ground_truths={"gt-1": ground_truth},
                contract=mock.MagicMock(),
            )
        assert "sample_start" in caplog.text
        assert "asset_count=1" in caplog.text
