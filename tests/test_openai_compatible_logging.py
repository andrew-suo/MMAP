"""Tests for OpenAI-compatible client runtime logging."""

import logging
from unittest import mock

import pytest

from mmap_optimizer.model.openai_compatible import OpenAICompatibleClient


class RecordingOpenAICompatibleClient(OpenAICompatibleClient):
    """Test subclass that records payloads instead of making HTTP calls."""

    def __init__(self):
        super().__init__(base_url="https://example.test", api_key="secret", model="vision-model")
        self.payloads = []

    def _post_json(self, payload, *, timeout=120):
        self.payloads.append(payload)
        return {"id": "resp_1", "choices": [{"message": {"content": '{"result":"OK"}'}}], "usage": {"total_tokens": 10}}


class FailingOpenAICompatibleClient(OpenAICompatibleClient):
    """Test subclass that always fails."""

    def __init__(self):
        super().__init__(base_url="https://example.test", api_key="secret", model="vision-model")

    def _post_json(self, payload, *, timeout=120):
        raise ConnectionError("Network error")


class TestOpenAICompatibleLogging:
    """Tests for OpenAI-compatible client logging."""

    def test_model_request_start_logged(self, caplog):
        """model_request_start should be logged on request."""
        client = RecordingOpenAICompatibleClient()
        with caplog.at_level(logging.INFO):
            client.complete(
                messages=[{"role": "system", "content": "test"}, {"role": "user", "content": "hello"}],
                model_config={"temperature": 0.5, "max_tokens": 100},
            )
        assert "model_request_start" in caplog.text
        assert "model=vision-model" in caplog.text
        assert "temperature=0.5" in caplog.text
        assert "max_tokens=100" in caplog.text

    def test_model_response_done_logged(self, caplog):
        """model_response_done should be logged after successful response."""
        client = RecordingOpenAICompatibleClient()
        with caplog.at_level(logging.INFO):
            client.complete(
                messages=[{"role": "user", "content": "hello"}],
            )
        assert "model_response_done" in caplog.text
        assert "duration_ms=" in caplog.text
        assert "response_chars=" in caplog.text

    def test_model_request_failed_logs_exception(self, caplog):
        """model_request_failed should log exception on error."""
        client = FailingOpenAICompatibleClient()
        with caplog.at_level(logging.INFO):
            with pytest.raises(ConnectionError):
                client.complete(messages=[{"role": "user", "content": "hello"}])
        assert "model_request_failed" in caplog.text
        assert "ConnectionError" in caplog.text

    def test_no_api_key_in_logs(self, caplog):
        """API key should never appear in logs."""
        client = RecordingOpenAICompatibleClient()
        with caplog.at_level(logging.INFO):
            client.complete(messages=[{"role": "user", "content": "hello"}])
        assert "secret" not in caplog.text
        assert "api_key" not in caplog.text or "<REDACTED>" in caplog.text

    def test_no_authorization_in_logs(self, caplog):
        """Authorization header should never appear in logs."""
        client = RecordingOpenAICompatibleClient()
        with caplog.at_level(logging.INFO):
            client.complete(messages=[{"role": "user", "content": "hello"}])
        # The actual API key value "secret" should not appear
        assert "secret" not in caplog.text

    def test_no_full_messages_in_logs(self, caplog):
        """Full message content should not appear in INFO logs."""
        client = RecordingOpenAICompatibleClient()
        long_content = "x" * 300
        with caplog.at_level(logging.INFO):
            client.complete(
                messages=[{"role": "system", "content": long_content}, {"role": "user", "content": "test"}],
            )
        # The long content should be truncated or redacted at INFO level
        assert long_content not in caplog.text or "<BINARY_DATA>" in caplog.text or "<REDACTED>" in caplog.text

    def test_multimodal_request_logs_asset_count(self, caplog):
        """complete_multimodal should log asset_count."""
        client = RecordingOpenAICompatibleClient()
        with caplog.at_level(logging.INFO):
            client.complete_multimodal(
                messages=[{"role": "user", "content": "hello"}],
                assets=[],
            )
        assert "asset_count=0" in caplog.text

    def test_chat_template_kwargs_flag_logged(self, caplog):
        """chat_template_kwargs presence should be logged."""
        client = RecordingOpenAICompatibleClient()
        with caplog.at_level(logging.INFO):
            client.complete(
                messages=[{"role": "user", "content": "hello"}],
                model_config={"chat_template_kwargs": {"enable_thinking": True}},
            )
        assert "has_chat_template_kwargs=True" in caplog.text

    def test_response_format_flag_logged(self, caplog):
        """has_response_format should be logged."""
        client = RecordingOpenAICompatibleClient()
        with caplog.at_level(logging.INFO):
            client.complete(
                messages=[{"role": "user", "content": "hello"}],
                response_format={"type": "json_object"},
            )
        assert "has_response_format=True" in caplog.text


class TestOpenAICompatibleErrorLogging:
    """Tests for OpenAI-compatible error logging."""

    def test_error_includes_duration_ms(self, caplog):
        """Error logs should include duration_ms."""
        client = FailingOpenAICompatibleClient()
        with caplog.at_level(logging.INFO):
            with pytest.raises(ConnectionError):
                client.complete(messages=[{"role": "user", "content": "hello"}])
        assert "duration_ms=" in caplog.text

    def test_error_includes_model_name(self, caplog):
        """Error logs should include model name."""
        client = FailingOpenAICompatibleClient()
        with caplog.at_level(logging.INFO):
            with pytest.raises(ConnectionError):
                client.complete(messages=[{"role": "user", "content": "hello"}])
        assert "model=vision-model" in caplog.text

    def test_exception_type_in_error_log(self, caplog):
        """Error logs should include exception type."""
        client = FailingOpenAICompatibleClient()
        with caplog.at_level(logging.INFO):
            with pytest.raises(ConnectionError):
                client.complete(messages=[{"role": "user", "content": "hello"}])
        # Should use logger.exception which includes traceback, but at minimum should have the type name
        assert "ConnectionError" in caplog.text
