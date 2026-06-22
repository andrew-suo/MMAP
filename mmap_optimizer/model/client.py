from __future__ import annotations

import json

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ModelResponse:
    raw_output: str
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
        # Build prompt_text from all messages except the last user message
        # (which is the current sample payload containing mock_prompt_outputs rules)
        prompt_parts: list[str] = []
        last_user_idx = None
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].get("role") == "user":
                last_user_idx = idx
                break
        for idx, message in enumerate(messages):
            if idx == last_user_idx:
                continue
            prompt_parts.append(self._extract_text(message.get("content", "")))
        prompt_text = "\n".join(prompt_parts)
        for message in reversed(messages):
            content = message.get("content")
            content_dict = self._parse_content(content)
            if content_dict is not None:
                for rule in content_dict.get("mock_prompt_outputs", []) or []:
                    contains_all = rule.get("contains_all")
                    if contains_all and all(fragment in prompt_text for fragment in contains_all):
                        return ModelResponse(raw_output=rule["output"])
                    contains = rule.get("contains")
                    if contains and contains in prompt_text:
                        return ModelResponse(raw_output=rule["output"])
                if content_dict.get("mock_output") is not None:
                    return ModelResponse(raw_output=content_dict["mock_output"])
        return ModelResponse(raw_output=self.default_output)

    def _extract_text(self, content: Any) -> str:
        """Extract text from message content (string or list of content parts)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        parts.append(str(part.get("image_url", {}).get("url", "")))
                    else:
                        parts.append(json.dumps(part, ensure_ascii=False))
                else:
                    parts.append(str(part))
            return "\n".join(parts)
        return str(content)

    def _parse_content(self, content: Any) -> dict | None:
        if isinstance(content, dict):
            return content
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return None
        return None

    def complete_multimodal(self, messages: list[dict[str, Any]], assets: list[Any], model_config: dict[str, Any] | None = None, response_format: Any | None = None) -> ModelResponse:
        return self.complete(messages, model_config, response_format)
