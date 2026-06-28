import os

import pytest

from mmap_optimizer.core.config import ModelConfig, RefactoredConfig
from mmap_optimizer.executors.factory import create_executors
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


def test_create_executors_exposes_runtime_model_config():
    executors = create_executors(
        {
            "run": {"output_dir": "runs/test"},
            "models": {
                "extraction": {
                    "provider": "mock",
                    "model": "extractor",
                    "temperature": 0.1,
                    "max_tokens": 111,
                    "request_timeout": 22,
                },
                "optimizer": {
                    "provider": "mock",
                    "model": "optimizer",
                    "temperature": 0.7,
                    "max_tokens": 222,
                    "timeout": 33,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            },
        },
        use_mock=None,
    )

    assert executors["extraction_model_config"]["max_tokens"] == 111
    assert executors["extraction_model_config"]["timeout"] == 22
    assert executors["optimizer_model_config"]["max_tokens"] == 222
    assert executors["optimizer_model_config"]["temperature"] == 0.7
    assert executors["optimizer_model_config"]["chat_template_kwargs"] == {
        "enable_thinking": False
    }


def test_default_dataset_path_points_to_existing_smoke_data():
    config = RefactoredConfig()

    assert config.dataset.path == "data/smoke_samples.jsonl"
