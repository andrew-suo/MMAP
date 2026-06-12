from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ModelResponse:
    raw_output: str
    parsed_output: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelClient(Protocol):
    def complete(self, messages: list[dict[str, Any]], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> ModelResponse:
        ...

    def complete_multimodal(self, messages: list[dict[str, Any]], assets: list[Any], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> ModelResponse:
        ...


class MockModelClient:
    """Deterministic test client. Returns a configured response or the sample mock_output."""

    def __init__(self, default_output: str = '{"result":"OK","confidence":1.0,"evidence":[],"used_prompt_sections":[]}'):
        self.default_output = default_output

    def complete(self, messages: list[dict[str, Any]], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> ModelResponse:
        prompt_text = "\n".join(str(message.get("content", "")) for message in messages if message.get("role") == "system")
        for message in reversed(messages):
            content = message.get("content")
            if isinstance(content, dict):
                for rule in content.get("mock_prompt_outputs", []) or []:
                    contains = rule.get("contains")
                    if contains and contains in prompt_text:
                        return ModelResponse(raw_output=rule["output"])
                if content.get("mock_output") is not None:
                    return ModelResponse(raw_output=content["mock_output"])
        return ModelResponse(raw_output=self.default_output)

    def complete_multimodal(self, messages: list[dict[str, Any]], assets: list[Any], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> ModelResponse:
        return self.complete(messages, model_config, response_format)
