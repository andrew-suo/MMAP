from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.patch.alignment import PatchAlignmentEngine
from mmap_optimizer.prompt.ir import PromptIR
from mmap_optimizer.templates import build_default_template_registry


@dataclass
class PatchRepairResult:
    repaired_patch: dict[str, Any]
    repaired: bool
    unresolved_fields: list[str]
    raw_output: str | None = None
    failure_reason: str | None = None


class PatchRepairEngine:
    def __init__(self, model_client: ModelClient | None = None, model_config: dict[str, Any] | None = None):
        self.model_client = model_client
        self.model_config = model_config or {}
        self.registry = build_default_template_registry()

    def repair_locator(self, *, patch: dict[str, Any], prompt_ir: PromptIR, failure_info: str) -> PatchRepairResult:
        candidate = dict(patch)
        raw_output: str | None = None
        if self.model_client is not None:
            template = self.registry.get("patch_translation_retry")
            response = self.model_client.complete(
                [
                    {"role": "system", "content": template.render(failure_info=failure_info, prompt_structure=_prompt_structure(prompt_ir), current_prompt=_prompt_text(prompt_ir), patch_json=json.dumps(patch, ensure_ascii=False))},
                    {"role": "user", "content": {"failure_info": failure_info, "patch": patch}},
                ],
                model_config=self.model_config,
                response_format=template.output_contract,
            )
            raw_output = response.raw_output
            try:
                parsed = json.loads(response.raw_output)
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                    candidate = parsed[0]
            except json.JSONDecodeError:
                pass
        alignment = PatchAlignmentEngine().align_patch_location(candidate, prompt_ir)
        return PatchRepairResult(
            repaired_patch=alignment.aligned_patch,
            repaired=alignment.changed and not alignment.unresolved,
            unresolved_fields=alignment.unresolved_fields,
            raw_output=raw_output,
            failure_reason=None if not alignment.unresolved else "UNRESOLVED_LOCATOR",
        )


def _prompt_structure(prompt_ir: PromptIR) -> str:
    return "\n".join(f"- {section.id}: {section.name or section.type}" for section in prompt_ir.sections)


def _prompt_text(prompt_ir: PromptIR) -> str:
    return "\n\n".join(section.content for section in prompt_ir.sections if section.rendering_enabled)
