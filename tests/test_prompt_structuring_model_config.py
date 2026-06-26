from __future__ import annotations

from pathlib import Path

from mmap_optimizer.model.client import ModelResponse
from mmap_optimizer.phases.prompt_structuring import (
    PromptStructuringConfig,
    PromptStructuringPhase,
)


class RecordingClient:
    def __init__(self):
        self.calls = []

    def complete(self, messages, model_config=None, response_format=None):
        self.calls.append({
            "messages": messages,
            "model_config": model_config,
            "response_format": response_format,
        })
        return ModelResponse(raw_output="# Task\n\nStandardized prompt.")


def test_prompt_structuring_passes_model_config_to_standardization(tmp_path: Path):
    standardization_prompt = tmp_path / "standardize.txt"
    standardization_prompt.write_text("Rewrite:\n{original_prompt}", encoding="utf-8")
    client = RecordingClient()
    model_config = {
        "model": "optimizer-model",
        "temperature": 0.7,
        "max_tokens": 1234,
        "timeout": 55,
    }
    phase = PromptStructuringPhase(
        PromptStructuringConfig(
            enabled=True,
            use_model_when_structure_poor=True,
            standardization_prompt_path=str(standardization_prompt),
        ),
        model_client=client,
        model_config=model_config,
    )

    phase._parse_and_standardize(
        "plain text without headings",
        prompt_type="analysis",
        prompt_id="p1",
    )

    assert client.calls
    assert client.calls[0]["model_config"] == model_config
