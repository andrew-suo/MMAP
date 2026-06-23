import os
import ssl
from unittest import mock

from mmap_optimizer.config import model_config_from_mapping, ModelConfig
from mmap_optimizer.model.openai_compatible import OpenAICompatibleClient


def test_openai_compatible_client_default_verify_ssl():
    client = OpenAICompatibleClient(base_url="https://example.test")
    assert client.verify_ssl is True


def test_openai_compatible_client_explicit_verify_ssl_true():
    client = OpenAICompatibleClient(base_url="https://example.test", verify_ssl=True)
    assert client.verify_ssl is True


def test_openai_compatible_client_explicit_verify_ssl_false():
    client = OpenAICompatibleClient(base_url="https://example.test", verify_ssl=False)
    assert client.verify_ssl is False


def test_openai_compatible_client_from_env_default_verify_ssl():
    os.environ["TEST_KEY"] = "test-value"
    try:
        client = OpenAICompatibleClient(
            base_url="https://example.test", api_key=os.environ.get("TEST_KEY")
        )
        assert client.verify_ssl is True
    finally:
        del os.environ["TEST_KEY"]


def test_openai_compatible_client_from_env_explicit_verify_ssl():
    os.environ["TEST_KEY"] = "test-value"
    try:
        client = OpenAICompatibleClient(
            base_url="https://example.test", api_key=os.environ.get("TEST_KEY"), verify_ssl=False
        )
        assert client.verify_ssl is False
    finally:
        del os.environ["TEST_KEY"]


def test_post_json_with_verify_ssl_true_does_not_create_context():
    client = OpenAICompatibleClient(base_url="https://example.test", verify_ssl=True)
    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["context"] = context
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value.read.return_value = b'{"choices": [{"message": {"content": "OK"}}]}'
        return mock_resp

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client._post_json({"test": "data"})

    assert captured["context"] is None


def test_post_json_with_verify_ssl_false_creates_insecure_context():
    client = OpenAICompatibleClient(base_url="https://example.test", verify_ssl=False)
    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["context"] = context
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value.read.return_value = b'{"choices": [{"message": {"content": "OK"}}]}'
        return mock_resp

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client._post_json({"test": "data"})

    assert captured["context"] is not None
    assert captured["context"].verify_mode == ssl.CERT_NONE
    assert captured["context"].check_hostname is False


def test_model_config_default_verify_ssl():
    config = ModelConfig()
    assert config.verify_ssl is True


def test_model_config_from_mapping_default_verify_ssl():
    config = model_config_from_mapping({})
    assert config.verify_ssl is True


def test_model_config_from_mapping_verify_ssl_true():
    config = model_config_from_mapping({"verify_ssl": True})
    assert config.verify_ssl is True


def test_model_config_from_mapping_verify_ssl_false():
    config = model_config_from_mapping({"verify_ssl": False})
    assert config.verify_ssl is False


def test_model_config_from_mapping_ssl_verify_alias():
    config = model_config_from_mapping({"ssl_verify": False})
    assert config.verify_ssl is False


def test_model_config_from_mapping_verify_ssl_string_true():
    config = model_config_from_mapping({"verify_ssl": "true"})
    assert config.verify_ssl is True


def test_model_config_from_mapping_verify_ssl_string_false():
    config = model_config_from_mapping({"verify_ssl": "false"})
    assert config.verify_ssl is False