"""Tests for AnalysisRunner user content JSON serialization."""

import json
from unittest import mock

import pytest

from mmap_optimizer.analysis.runner import AnalysisRunner
from mmap_optimizer.evaluation.evaluator import EvaluationRecord
from mmap_optimizer.orchestration.records import RunRecord
from mmap_optimizer.prompt.version import PromptVersion


class RecordingModelClient:
    """Test model client that records messages passed to complete()."""

    def __init__(self):
        self.call_args = []
        self.response_count = 0

    def complete(self, messages, model_config=None):
        self.call_args.append({"messages": messages, "model_config": model_config})
        self.response_count += 1
        return mock.MagicMock(raw_output='{"judgement":{"is_correct":false},"patch_candidates":[]}')


def make_mock_prompt(text: str = "system prompt") -> PromptVersion:
    """Create a mock prompt for testing."""
    mock_rendered = mock.MagicMock()
    mock_rendered.text = text
    mock_rendered.text_hash = "test-hash"

    prompt = mock.MagicMock(spec=PromptVersion)
    prompt.id = "test-analysis-prompt"
    prompt.render.return_value = mock_rendered
    return prompt


def make_eval_record(sample_id: str = "sample-1", status: str = "incorrect") -> EvaluationRecord:
    """Create a test EvaluationRecord."""
    return EvaluationRecord(
        id=f"eval-{sample_id}",
        round_id="round-1",
        run_id=f"run-{sample_id}",
        sample_id=sample_id,
        ground_truth_id="gt-1",
        parse_success=True,
        schema_valid=True,
        primary_answer_correct=False,
        overall_status=status,
    )


def make_run_record(sample_id: str = "sample-1") -> RunRecord:
    """Create a test RunRecord."""
    return RunRecord(
        id=f"run-round-1-{sample_id}",
        round_id="round-1",
        run_type="extraction",
        sample_id=sample_id,
        prompt_version_id="test-extraction-prompt",
        rendered_prompt_hash="test-hash",
        model_id="test-model",
        raw_output='{"result":"ok"}',
        success=True,
    )


class TestAnalysisRunnerUserContent:
    """Tests for AnalysisRunner user content JSON serialization."""

    def test_user_content_is_string(self):
        """User message content should be a string, not a dict."""
        model_client = RecordingModelClient()
        runner = AnalysisRunner(model_client=model_client, model_id="test-model")
        eval_record = make_eval_record("sample-1")
        extraction_runs = {"sample-1": make_run_record("sample-1")}
        sample_metadata = {"sample-1": {"mock_analysis_output": None}}
        analysis_prompt = make_mock_prompt("You are an analysis assistant.")

        runner.analyze_errors(
            round_id="round-1",
            error_evaluations=[eval_record],
            extraction_runs=extraction_runs,
            sample_metadata=sample_metadata,
            analysis_prompt=analysis_prompt,
        )

        assert len(model_client.call_args) == 1
        messages = model_client.call_args[0]["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert isinstance(messages[1]["content"], str)

    def test_user_content_json_loadable(self):
        """User message content should be valid JSON that can be loaded."""
        model_client = RecordingModelClient()
        runner = AnalysisRunner(model_client=model_client, model_id="test-model")
        eval_record = make_eval_record("sample-xyz")
        extraction_runs = {"sample-xyz": make_run_record("sample-xyz")}
        sample_metadata = {"sample-xyz": {"mock_analysis_output": "analysis output here"}}
        analysis_prompt = make_mock_prompt("You are an analysis assistant.")

        runner.analyze_errors(
            round_id="round-1",
            error_evaluations=[eval_record],
            extraction_runs=extraction_runs,
            sample_metadata=sample_metadata,
            analysis_prompt=analysis_prompt,
        )

        messages = model_client.call_args[0]["messages"]
        payload = json.loads(messages[1]["content"])
        assert payload["sample_id"] == "sample-xyz"
        assert "evaluation" in payload
        assert "mock_output" in payload
        assert payload["mock_output"] == "analysis output here"

    def test_chinese_not_ascii_escaped(self):
        """Chinese characters should not be ASCII-escaped in user content."""
        model_client = RecordingModelClient()
        runner = AnalysisRunner(model_client=model_client, model_id="test-model")
        eval_record = make_eval_record("sample-cn")
        extraction_runs = {"sample-cn": make_run_record("sample-cn")}
        sample_metadata = {"sample-cn": {"mock_analysis_output": "分析结果：中文测试"}}
        analysis_prompt = make_mock_prompt("你是一个分析助手。")

        runner.analyze_errors(
            round_id="round-1",
            error_evaluations=[eval_record],
            extraction_runs=extraction_runs,
            sample_metadata=sample_metadata,
            analysis_prompt=analysis_prompt,
        )

        messages = model_client.call_args[0]["messages"]
        content = messages[1]["content"]
        assert "中文" in content or "分析结果" in content
        assert "\\u4e2d" not in content
        assert "\\u5206" not in content

    def test_no_bare_dict_content(self):
        """User content should not be a raw dict."""
        model_client = RecordingModelClient()
        runner = AnalysisRunner(model_client=model_client, model_id="test-model")
        eval_record = make_eval_record("sample-dict")
        extraction_runs = {"sample-dict": make_run_record("sample-dict")}
        sample_metadata = {"sample-dict": {"mock_analysis_output": None}}
        analysis_prompt = make_mock_prompt("system")

        runner.analyze_errors(
            round_id="round-1",
            error_evaluations=[eval_record],
            extraction_runs=extraction_runs,
            sample_metadata=sample_metadata,
            analysis_prompt=analysis_prompt,
        )

        messages = model_client.call_args[0]["messages"]
        assert not isinstance(messages[1]["content"], dict)

    def test_model_client_complete_called(self):
        """model_client.complete() should be called once per error evaluation."""
        model_client = RecordingModelClient()
        runner = AnalysisRunner(model_client=model_client, model_id="test-model")
        eval1 = make_eval_record("sample-1")
        eval2 = make_eval_record("sample-2")
        extraction_runs = {
            "sample-1": make_run_record("sample-1"),
            "sample-2": make_run_record("sample-2"),
        }
        sample_metadata = {
            "sample-1": {"mock_analysis_output": None},
            "sample-2": {"mock_analysis_output": None},
        }
        analysis_prompt = make_mock_prompt("system")

        runner.analyze_errors(
            round_id="round-1",
            error_evaluations=[eval1, eval2],
            extraction_runs=extraction_runs,
            sample_metadata=sample_metadata,
            analysis_prompt=analysis_prompt,
        )

        assert model_client.response_count == 2
        assert len(model_client.call_args) == 2

    def test_sample_id_preserved(self):
        """sample_id should be preserved in serialized user content."""
        model_client = RecordingModelClient()
        runner = AnalysisRunner(model_client=model_client, model_id="test-model")
        eval_record = make_eval_record("abc123")
        extraction_runs = {"abc123": make_run_record("abc123")}
        sample_metadata = {"abc123": {"mock_analysis_output": None}}
        analysis_prompt = make_mock_prompt("system")

        runner.analyze_errors(
            round_id="round-5",
            error_evaluations=[eval_record],
            extraction_runs=extraction_runs,
            sample_metadata=sample_metadata,
            analysis_prompt=analysis_prompt,
        )

        messages = model_client.call_args[0]["messages"]
        payload = json.loads(messages[1]["content"])
        assert payload["sample_id"] == "abc123"

    def test_evaluation_fields_preserved(self):
        """evaluation record fields should be preserved in serialized content."""
        model_client = RecordingModelClient()
        runner = AnalysisRunner(model_client=model_client, model_id="test-model")
        eval_record = make_eval_record("eval-fields", status="incorrect")
        extraction_runs = {"eval-fields": make_run_record("eval-fields")}
        sample_metadata = {"eval-fields": {"mock_analysis_output": None}}
        analysis_prompt = make_mock_prompt("system")

        runner.analyze_errors(
            round_id="round-1",
            error_evaluations=[eval_record],
            extraction_runs=extraction_runs,
            sample_metadata=sample_metadata,
            analysis_prompt=analysis_prompt,
        )

        messages = model_client.call_args[0]["messages"]
        payload = json.loads(messages[1]["content"])
        eval_data = payload["evaluation"]
        assert eval_data["sample_id"] == "eval-fields"
        assert eval_data["overall_status"] == "incorrect"
        assert eval_data["round_id"] == "round-1"

    def test_mock_output_none_handled(self):
        """mock_output=None should be handled gracefully."""
        model_client = RecordingModelClient()
        runner = AnalysisRunner(model_client=model_client, model_id="test-model")
        eval_record = make_eval_record("sample-none")
        extraction_runs = {"sample-none": make_run_record("sample-none")}
        sample_metadata = {"sample-none": {"mock_analysis_output": None}}
        analysis_prompt = make_mock_prompt("system")

        runner.analyze_errors(
            round_id="round-1",
            error_evaluations=[eval_record],
            extraction_runs=extraction_runs,
            sample_metadata=sample_metadata,
            analysis_prompt=analysis_prompt,
        )

        messages = model_client.call_args[0]["messages"]
        payload = json.loads(messages[1]["content"])
        assert payload["mock_output"] is None

    def test_system_prompt_unchanged(self):
        """System prompt should remain as plain string."""
        model_client = RecordingModelClient()
        runner = AnalysisRunner(model_client=model_client, model_id="test-model")
        eval_record = make_eval_record("sample-sys")
        extraction_runs = {"sample-sys": make_run_record("sample-sys")}
        sample_metadata = {"sample-sys": {"mock_analysis_output": None}}
        analysis_prompt = make_mock_prompt("SYSTEM PROMPT TEXT UNCHANGED")

        runner.analyze_errors(
            round_id="round-1",
            error_evaluations=[eval_record],
            extraction_runs=extraction_runs,
            sample_metadata=sample_metadata,
            analysis_prompt=analysis_prompt,
        )

        messages = model_client.call_args[0]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "SYSTEM PROMPT TEXT UNCHANGED"
        assert isinstance(messages[0]["content"], str)