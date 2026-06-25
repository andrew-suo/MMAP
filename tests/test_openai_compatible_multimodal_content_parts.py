"""Tests for OpenAI-compatible content parts format in OpenAICompatibleClient."""

import json
import ssl
from unittest import mock

import pytest

from mmap_optimizer.data.sample import SampleAsset
from mmap_optimizer.model.openai_compatible import OpenAICompatibleClient


class RecordingOpenAICompatibleClient(OpenAICompatibleClient):
    """Test client that records prepared messages."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prepared_messages = None

    def complete_multimodal(self, messages, assets=None, model_config=None, response_format=None):
        self.prepared_messages = self._messages_with_assets(list(messages), list(assets) if assets else [])
        return {"id": "test", "choices": [{"message": {"content": '{"result":"OK"}'}}], "usage": {"total_tokens": 10}}


def test_content_to_parts_string():
    """String content is converted to text part."""
    client = OpenAICompatibleClient(base_url="https://example.test")
    parts = client._content_to_parts("hello world")
    assert parts == [{"type": "text", "text": "hello world"}]


def test_content_to_parts_empty_string():
    """Empty string returns empty list."""
    client = OpenAICompatibleClient(base_url="https://example.test")
    parts = client._content_to_parts("")
    assert parts == []


def test_content_to_parts_dict():
    """Dict content is converted to text part with JSON."""
    client = OpenAICompatibleClient(base_url="https://example.test")
    parts = client._content_to_parts({"key": "value"})
    assert len(parts) == 1
    assert parts[0]["type"] == "text"
    parsed = json.loads(parts[0]["text"])
    assert parsed == {"key": "value"}


def test_content_to_parts_bare_dict_without_type():
    """Bare dict without 'type' field is converted to text part."""
    client = OpenAICompatibleClient(base_url="https://example.test")
    parts = client._content_to_parts([{"sample_id": "s1", "text_context": "test"}])
    assert len(parts) == 1
    assert parts[0]["type"] == "text"
    parsed = json.loads(parts[0]["text"])
    assert parsed == {"sample_id": "s1", "text_context": "test"}


def test_content_to_parts_valid_text_part():
    """Valid text part is preserved."""
    client = OpenAICompatibleClient(base_url="https://example.test")
    parts = client._content_to_parts([{"type": "text", "text": "hello"}])
    assert parts == [{"type": "text", "text": "hello"}]


def test_content_to_parts_valid_image_url_part():
    """Valid image_url part is preserved."""
    client = OpenAICompatibleClient(base_url="https://example.test")
    parts = client._content_to_parts([{"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}])
    assert parts == [{"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}]


def test_content_to_parts_mixed_list():
    """Mixed list with bare dict and image part."""
    client = OpenAICompatibleClient(base_url="https://example.test")
    parts = client._content_to_parts([
        {"sample_id": "s1"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
    ])
    assert len(parts) == 2
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"


def test_content_to_parts_non_string_non_dict():
    """Non-string, non-dict elements are converted to text parts."""
    client = OpenAICompatibleClient(base_url="https://example.test")
    parts = client._content_to_parts([123, None, True])
    assert len(parts) == 3
    for part in parts:
        assert part["type"] == "text"


def test_content_to_parts_chinese_not_escaped():
    """Chinese characters are preserved without escaping."""
    client = OpenAICompatibleClient(base_url="https://example.test")
    parts = client._content_to_parts([{"中文": "测试"}])
    assert parts[0]["type"] == "text"
    assert "中文" in parts[0]["text"]
    assert "测试" in parts[0]["text"]


def test_messages_with_assets_string_content():
    """String content becomes text part when assets are present."""
    client = RecordingOpenAICompatibleClient(base_url="https://example.test")
    messages = [{"role": "user", "content": '{"sample_id": "s1"}'}]
    assets = [SampleAsset(id="a1", sample_id="s1", uri="https://example.com/test.png", mime_type="image/png")]

    client.complete_multimodal(messages, assets)

    user_msg = client.prepared_messages[0]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)
    assert len(user_msg["content"]) == 2
    assert user_msg["content"][0]["type"] == "text"
    assert user_msg["content"][1]["type"] == "image_url"


def test_messages_with_assets_list_content():
    """List content is properly processed when assets are present."""
    client = RecordingOpenAICompatibleClient(base_url="https://example.test")
    messages = [{"role": "user", "content": [{"type": "text", "text": "existing"}]}]
    assets = [SampleAsset(id="a1", sample_id="s1", uri="https://example.com/test.png", mime_type="image/png")]

    client.complete_multimodal(messages, assets)

    user_msg = client.prepared_messages[0]
    assert len(user_msg["content"]) == 2
    assert user_msg["content"][0]["type"] == "text"
    assert user_msg["content"][1]["type"] == "image_url"


def test_messages_with_assets_bare_dict_in_list():
    """Bare dict in list content is converted to text part."""
    client = RecordingOpenAICompatibleClient(base_url="https://example.test")
    messages = [{"role": "user", "content": [{"sample_id": "s1", "text": "context"}]}]
    assets = [SampleAsset(id="a1", sample_id="s1", uri="https://example.com/test.png", mime_type="image/png")]

    client.complete_multimodal(messages, assets)

    user_msg = client.prepared_messages[0]
    assert len(user_msg["content"]) == 2
    assert user_msg["content"][0]["type"] == "text"
    parsed = json.loads(user_msg["content"][0]["text"])
    assert parsed == {"sample_id": "s1", "text": "context"}
    assert user_msg["content"][1]["type"] == "image_url"


def test_messages_with_assets_no_assets_returns_original():
    """When no assets, original messages are returned."""
    client = RecordingOpenAICompatibleClient(base_url="https://example.test")
    messages = [{"role": "user", "content": "hello"}]

    result = client._messages_with_assets(messages, [])

    assert result == messages


def test_messages_with_assets_multiple_images():
    """Multiple images are all added as image_url parts."""
    client = RecordingOpenAICompatibleClient(base_url="https://example.test")
    messages = [{"role": "user", "content": '{"sample_id": "s1"}'}]
    assets = [
        SampleAsset(id="a1", sample_id="s1", uri="https://example.com/test1.png", mime_type="image/png"),
        SampleAsset(id="a2", sample_id="s1", uri="https://example.com/test2.png", mime_type="image/png"),
    ]

    client.complete_multimodal(messages, assets)

    user_msg = client.prepared_messages[0]
    assert len(user_msg["content"]) == 3
    assert user_msg["content"][0]["type"] == "text"
    assert user_msg["content"][1]["type"] == "image_url"
    assert user_msg["content"][2]["type"] == "image_url"


def test_all_content_parts_have_type():
    """All content parts must have a 'type' field."""
    client = RecordingOpenAICompatibleClient(base_url="https://example.test")

    test_cases = [
        [{"sample_id": "s1"}],
        [{"type": "text", "text": "hello"}],
        [{"sample_id": "s1"}, {"type": "image_url", "image_url": {"url": "https://example.com/x"}}],
        ["plain text"],
        [{"key": "value"}, {"another": "dict"}],
    ]

    for content in test_cases:
        messages = [{"role": "user", "content": content}]
        assets = [SampleAsset(id="a1", sample_id="s1", uri="https://example.com/test.png", mime_type="image/png")]

        client.complete_multimodal(messages, assets)

        user_msg = client.prepared_messages[0]
        for part in user_msg["content"]:
            assert "type" in part, f"Content part missing 'type' field: {part}"
