"""Tests for chat_template_kwargs in OpenAI-compatible payload."""

from mmap_optimizer.config import ModelConfig, model_config_from_mapping
from mmap_optimizer.model.openai_compatible import OpenAICompatibleClient


def test_build_payload_default_enable_thinking_false():
    """_build_payload() without chat_template_kwargs should inject default."""
    client = OpenAICompatibleClient(base_url="https://example.test", model="test-model")
    payload = client._build_payload(messages=[{"role": "user", "content": "hi"}])
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_build_payload_explicit_enable_thinking_true():
    """Explicit chat_template_kwargs should override default."""
    client = OpenAICompatibleClient(base_url="https://example.test", model="test-model")
    payload = client._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        model_config={"chat_template_kwargs": {"enable_thinking": True}},
    )
    assert payload["chat_template_kwargs"] == {"enable_thinking": True}


def test_build_payload_explicit_empty_dict_preserved():
    """Explicit empty dict should be preserved, not replaced with default."""
    client = OpenAICompatibleClient(base_url="https://example.test", model="test-model")
    payload = client._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        model_config={"chat_template_kwargs": {}},
    )
    assert payload["chat_template_kwargs"] == {}


def test_build_payload_response_format_preserved():
    """response_format should still be included in payload."""
    client = OpenAICompatibleClient(base_url="https://example.test", model="test-model")
    payload = client._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        response_format={"type": "json_object"},
    )
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_build_payload_response_format_with_explicit_kwargs():
    """Both response_format and chat_template_kwargs should coexist."""
    client = OpenAICompatibleClient(base_url="https://example.test", model="test-model")
    payload = client._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        model_config={"chat_template_kwargs": {"enable_thinking": True, "temperature": 0.5}},
        response_format={"type": "json_object"},
    )
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["chat_template_kwargs"] == {"enable_thinking": True, "temperature": 0.5}


def test_build_payload_model_and_temperature_preserved():
    """Existing model/temperature/max_tokens logic must remain unchanged."""
    client = OpenAICompatibleClient(base_url="https://example.test", model="default-model")
    payload = client._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        model_config={"model": "override-model", "temperature": 0.7, "max_tokens": 512},
    )
    assert payload["model"] == "override-model"
    assert payload["temperature"] == 0.7
    assert payload["max_tokens"] == 512
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_build_payload_falls_back_to_self_model():
    """When model_config has no model, self.model should be used."""
    client = OpenAICompatibleClient(base_url="https://example.test", model="self-model")
    payload = client._build_payload(messages=[{"role": "user", "content": "hi"}])
    assert payload["model"] == "self-model"


def test_complete_includes_chat_template_kwargs():
    """complete() path should also include chat_template_kwargs in payload."""
    client = OpenAICompatibleClient(base_url="https://example.test", model="test-model")
    payload = client._build_payload(messages=[{"role": "user", "content": "hi"}])
    assert "chat_template_kwargs" in payload


def test_model_config_default_has_none_chat_template_kwargs():
    """ModelConfig default should have chat_template_kwargs=None."""
    config = ModelConfig()
    assert config.chat_template_kwargs is None


def test_model_config_from_mapping_with_chat_template_kwargs():
    """model_config_from_mapping should parse chat_template_kwargs."""
    config = model_config_from_mapping({
        "provider": "openai_compatible",
        "model": "test-model",
        "base_url": "https://example.test",
        "chat_template_kwargs": {"enable_thinking": False},
    })
    assert config.chat_template_kwargs == {"enable_thinking": False}


def test_model_config_from_mapping_without_chat_template_kwargs():
    """model_config_from_mapping without chat_template_kwargs should be None."""
    config = model_config_from_mapping({
        "provider": "openai_compatible",
        "model": "test-model",
    })
    assert config.chat_template_kwargs is None


def test_complete_multimodal_includes_chat_template_kwargs():
    """complete_multimodal() path should also include chat_template_kwargs."""
    client = OpenAICompatibleClient(base_url="https://example.test", model="test-model")
    # Build payload directly via the same code path complete_multimodal uses
    prepared_messages = client._messages_with_assets(
        [{"role": "user", "content": "hi"}],
        [],
    )
    payload = client._build_payload(messages=prepared_messages)
    assert "chat_template_kwargs" in payload
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_build_payload_with_ssl_config_preserved():
    """SSL verify_ssl should remain independent from chat_template_kwargs."""
    client = OpenAICompatibleClient(base_url="https://example.test", model="test-model", verify_ssl=False)
    payload = client._build_payload(messages=[{"role": "user", "content": "hi"}])
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert client.verify_ssl is False
