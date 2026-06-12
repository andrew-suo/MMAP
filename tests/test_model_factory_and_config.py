import os

import pytest

from mmap_optimizer.core.config import ModelConfig, optimizer_config_from_mapping
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


def test_optimizer_config_from_mapping_reads_dual_model_config():
    config = optimizer_config_from_mapping(
        {
            "run_dir": "runs/prod",
            "models": {
                "extraction": {
                    "provider": "openai_compatible",
                    "base_url": "https://extract.example/v1",
                    "api_key_env": "EXTRACTION_KEY",
                    "model": "vision-extractor",
                    "temperature": 0.1,
                    "max_tokens": 1000,
                },
                "optimizer": {
                    "provider": "openai_compatible",
                    "base_url": "https://opt.example/v1",
                    "api_key_env": "OPTIMIZER_KEY",
                    "model": "patch-optimizer",
                },
            },
            "text_optimization": {"batch_size": 7, "max_rounds": 3},
            "dynamic_validation": {"batch_size": 11},
            "fewshot": {"enabled": True, "max_rounds": 2, "max_slots": 4, "min_accuracy_delta": 0.2},
        }
    )

    assert config.run_dir == "runs/prod"
    assert config.batch_size == 7
    assert config.dynamic_validation_batch_size == 11
    assert config.max_text_rounds == 3
    assert config.fewshot_enabled is True
    assert config.fewshot_max_rounds == 2
    assert config.fewshot_max_slots == 4
    assert config.fewshot_min_accuracy_delta == 0.2
    assert config.extraction_model.base_url == "https://extract.example/v1"
    assert config.extraction_model.model == "vision-extractor"
    assert config.extraction_model.temperature == 0.1
    assert config.extraction_model.max_tokens == 1000
    assert config.optimizer_model.base_url == "https://opt.example/v1"
    assert config.optimizer_model.model == "patch-optimizer"
