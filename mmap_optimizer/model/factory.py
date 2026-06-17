from __future__ import annotations

import os

from mmap_optimizer.core.config import ModelConfig
from .client import MockModelClient, ModelClient
from .openai_compatible import OpenAICompatibleClient


def build_model_client(config: ModelConfig) -> ModelClient:
    provider = (config.provider or "mock").lower()
    if provider == "mock":
        return MockModelClient()
    if provider in {"openai_compatible", "openai-compatible", "openai"}:
        if not config.base_url:
            raise ValueError("OpenAI-compatible model config requires base_url")
        if not config.model:
            raise ValueError("OpenAI-compatible model config requires model")
        api_key = config.api_key or (os.environ.get(config.api_key_env) if config.api_key_env else None)
        return OpenAICompatibleClient(base_url=config.base_url, api_key=api_key, model=config.model, verify_ssl=config.verify_ssl)
    raise ValueError(f"Unsupported model provider: {config.provider}")
