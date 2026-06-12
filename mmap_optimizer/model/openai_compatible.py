from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from .client import ModelResponse


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str | None = None, model: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    @classmethod
    def from_env(cls, base_url: str, api_key_env: str, model: str | None = None) -> "OpenAICompatibleClient":
        return cls(base_url=base_url, api_key=os.environ.get(api_key_env), model=model)

    def complete(self, messages: list[dict[str, Any]], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> ModelResponse:
        cfg = model_config or {}
        payload: dict[str, Any] = {
            "model": cfg.get("model") or self.model,
            "messages": messages,
            "temperature": cfg.get("temperature", 0),
            "max_tokens": cfg.get("max_tokens", 2048),
        }
        if response_format is not None:
            payload["response_format"] = response_format
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return ModelResponse(raw_output=content, metadata={"usage": body.get("usage")})

    def complete_multimodal(self, messages: list[dict[str, Any]], assets: list[Any], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> ModelResponse:
        return self.complete(messages, model_config, response_format)
