"""Tests for runtime logging utilities."""

import logging

import pytest

from mmap_optimizer.logging import _safe_log_dict, get_logger, log_progress, log_stage, set_log_level


class TestSafeLogDict:
    """Tests for _safe_log_dict function."""

    def test_redacts_api_key(self):
        """api_key should be redacted in logs."""
        result = _safe_log_dict({"api_key": "secret123"})
        assert "secret123" not in result
        assert "api_key=<REDACTED>" in result

    def test_redacts_authorization(self):
        """Authorization header should be redacted."""
        result = _safe_log_dict({"Authorization": "Bearer token123"})
        assert "token123" not in result
        assert "Authorization=<REDACTED>" in result

    def test_redacts_auth(self):
        """auth field should be redacted."""
        result = _safe_log_dict({"auth": "secret"})
        assert "secret" not in result
        assert "auth=<REDACTED>" in result

    def test_redacts_token(self):
        """token field should be redacted."""
        result = _safe_log_dict({"token": "jwt-token"})
        assert "jwt-token" not in result
        assert "token=<REDACTED>" in result

    def test_redacts_secret(self):
        """secret field should be redacted."""
        result = _safe_log_dict({"secret": "my-secret"})
        assert "my-secret" not in result
        assert "secret=<REDACTED>" in result

    def test_redacts_password(self):
        """password field should be redacted."""
        result = _safe_log_dict({"password": "pwd123"})
        assert "pwd123" not in result
        assert "password=<REDACTED>" in result

    def test_redacts_base64_images(self):
        """data:image base64 content should be redacted."""
        result = _safe_log_dict({"image": "data:image/png;base64,ABCDEF12345"})
        assert "ABCDEF12345" not in result
        assert "image=<BINARY_DATA>" in result

    def test_redacts_long_content(self):
        """Content over 5000 chars should be redacted."""
        long_content = "x" * 6000
        result = _safe_log_dict({"content": long_content})
        assert long_content not in result
        assert "<BINARY_DATA>" in result

    def test_truncates_long_values(self):
        """Values over max_value_len should be truncated."""
        result = _safe_log_dict({"long_field": "x" * 300}, max_value_len=200)
        assert "x" * 200 in result
        assert "x" * 300 not in result
        assert "..." in result

    def test_preserves_normal_values(self):
        """Normal values should be preserved."""
        result = _safe_log_dict({"model": "gpt-4", "temperature": 0.5})
        assert "model=gpt-4" in result
        assert "temperature=0.5" in result


class TestLogStage:
    """Tests for log_stage function."""

    def test_log_stage_without_kwargs(self, caplog):
        """log_stage should log stage name."""
        logger = get_logger("test_log_stage_no_kwargs")
        with caplog.at_level(logging.INFO):
            log_stage(logger, "round_start")
        assert "[stage=round_start]" in caplog.text

    def test_log_stage_with_kwargs(self, caplog):
        """log_stage should log stage name with kwargs."""
        logger = get_logger("test_log_stage_with_kwargs")
        with caplog.at_level(logging.INFO):
            log_stage(logger, "round_start", round=1, planned_rounds=5)
        assert "[stage=round_start" in caplog.text
        assert "round=1" in caplog.text
        assert "planned_rounds=5" in caplog.text

    def test_log_stage_redacts_sensitive(self, caplog):
        """log_stage should redact sensitive kwargs."""
        logger = get_logger("test_log_stage_redact")
        with caplog.at_level(logging.INFO):
            log_stage(logger, "model_request", api_key="secret123")
        assert "secret123" not in caplog.text
        assert "api_key=<REDACTED>" in caplog.text


class TestLogProgress:
    """Tests for log_progress function."""

    def test_log_progress_without_kwargs(self, caplog):
        """log_progress should log message."""
        logger = get_logger("test_log_progress_no_kwargs")
        with caplog.at_level(logging.INFO):
            log_progress(logger, "Processing started")
        assert "Processing started" in caplog.text

    def test_log_progress_with_kwargs(self, caplog):
        """log_progress should log message with extra data."""
        logger = get_logger("test_log_progress_with_kwargs")
        with caplog.at_level(logging.INFO):
            log_progress(logger, "model_request_start", model="gpt-4", duration_ms=150)
        assert "model_request_start" in caplog.text
        assert "model=gpt-4" in caplog.text
        assert "duration_ms=150" in caplog.text


class TestSetLogLevel:
    """Tests for set_log_level function."""

    def test_set_log_level_string(self, caplog):
        """set_log_level should accept string level."""
        logger = get_logger("test_set_level_string")
        set_log_level("DEBUG")
        with caplog.at_level(logging.DEBUG):
            logger.debug("debug message")
        assert "debug message" in caplog.text

    def test_set_log_level_int(self, caplog):
        """set_log_level should accept int level."""
        logger = get_logger("test_set_level_int")
        set_log_level(logging.DEBUG)
        with caplog.at_level(logging.DEBUG):
            logger.debug("debug int message")
        assert "debug int message" in caplog.text


class TestLoggerRedactionIntegration:
    """Integration tests for logger redaction."""

    def test_logger_does_not_leak_api_key(self, caplog):
        """Complete logging flow should not leak api_key."""
        logger = get_logger("test_no_leak_api_key")
        with caplog.at_level(logging.INFO):
            log_stage(logger, "model_request", api_key="super-secret-key", model="gpt-4")
        assert "super-secret-key" not in caplog.text
        assert "api_key=<REDACTED>" in caplog.text

    def test_logger_does_not_leak_authorization(self, caplog):
        """Complete logging flow should not leak Authorization."""
        logger = get_logger("test_no_leak_auth")
        with caplog.at_level(logging.INFO):
            log_stage(logger, "model_request", Authorization="Bearer token123", model="gpt-4")
        assert "token123" not in caplog.text
        assert "Authorization=<REDACTED>" in caplog.text

    def test_logger_does_not_leak_base64_image(self, caplog):
        """Complete logging flow should not leak base64 image data."""
        logger = get_logger("test_no_leak_image")
        with caplog.at_level(logging.INFO):
            log_stage(logger, "model_request", image_data="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
        assert "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" not in caplog.text
        assert "<BINARY_DATA>" in caplog.text
