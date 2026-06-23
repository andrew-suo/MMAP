import os

import pytest

from mmap_optimizer.config import ModelConfig
from mmap_optimizer.model.factory import build_model_client
from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.model.openai_compatible import OpenAICompatibleClient


def test_build_model_client_supports_mock_provider():
    client = build_model_client(ModelConfig(provider="mock"))

    assert isinstance(client, MockModelClient)


def test_build_model_client_supports_openai_compatible_env_key(monkeypatch):
    monkeypatch.setenv("MMAP_TEST_API_KEY", "secret")

    client = build_model_client(
        ModelConfig(
            provider="openai_compatible",
            base_url="https://api.example.test/v1",
            api_key_env="MMAP_TEST_API_KEY",
            model="vision-model",
        )
    )

    assert isinstance(client, OpenAICompatibleClient)
    assert client.base_url == "https://api.example.test/v1"
    assert client.api_key == "secret"
    assert client.model == "vision-model"


def test_build_model_client_requires_base_url_for_openai_compatible():
    with pytest.raises(ValueError, match="base_url"):
        build_model_client(ModelConfig(provider="openai_compatible", model="vision-model"))
