from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.prompt.ir import PromptIR
from mmap_optimizer.templates import build_default_template_registry


class SemanticPatchProcessor:
    def __init__(self, model_client: ModelClient, model_config: dict[str, Any] | None = None):
        self.model_client = model_client
        self.model_config = model_config or {}
        self.registry = build_default_template_registry()

    def merge(self, patches: list[Patch], prompt_ir: PromptIR) -> list[Patch]:
        return self._process("patch_semantic_merge", patches, prompt_ir)

    def root_audit(self, patches: list[Patch], prompt_ir: PromptIR) -> list[Patch]:
        return self._process("patch_root_audit", patches, prompt_ir)

    def _process(self, template_id: str, patches: list[Patch], prompt_ir: PromptIR) -> list[Patch]:
        if not patches:
            return []
        template = self.registry.get(template_id)
        prompt = template.render(prompt_structure=_prompt_structure(prompt_ir), patches_json=json.dumps([_patch_to_dict(p) for p in patches], ensure_ascii=False, indent=2))
        response = self.model_client.complete(
            [{"role": "system", "content": prompt}, {"role": "user", "content": {"patches": [_patch_to_dict(p) for p in patches]}}],
            model_config=self.model_config,
            response_format=template.output_contract,
        )
        try:
            payload = json.loads(response.raw_output)
        except json.JSONDecodeError:
            return patches
        if not isinstance(payload, list):
            return patches
        converted = [_patch_from_dict(item, patches[index if index < len(patches) else -1]) for index, item in enumerate(payload) if isinstance(item, dict)]
        return converted or patches


def _prompt_structure(prompt_ir: PromptIR) -> str:
    lines = []
    for section in prompt_ir.sections:
        name = section.name or section.id
        lines.append(f"- {section.id}: {name} (type={section.type}, mutability={section.mutability})")
    return "\n".join(lines)


def _patch_to_dict(patch: Patch) -> dict[str, Any]:
    return {
        "id": patch.id,
        "type": patch.type,
        "status": patch.status,
        "target_prompt_type": patch.target_prompt_type,
        "base_version_id": patch.base_version_id,
        "section_id": patch.section_id,
        "operation_type": patch.operation_type,
        "operation_mode": patch.operation_mode,
        "intent_name": patch.intent_name,
        "intent_description": patch.intent_description,
        "patch_text": patch.patch_text,
        "rationale": patch.rationale,
        "source_sample_ids": patch.source_sample_ids,
        "source_analysis_ids": patch.source_analysis_ids,
        "risk_level": patch.risk_level,
        "possible_side_effects": patch.possible_side_effects,
    }


def _patch_from_dict(data: dict[str, Any], fallback: Patch) -> Patch:
    return replace(
        fallback,
        id=str(data.get("id") or fallback.id),
        type=str(data.get("type") or fallback.type),
        status=str(data.get("status") or fallback.status),
        target_prompt_type=str(data.get("target_prompt_type") or fallback.target_prompt_type),
        base_version_id=str(data.get("base_version_id") or fallback.base_version_id),
        section_id=str(data.get("section_id") or data.get("target_section") or fallback.section_id),
        operation_type=str(data.get("operation_type") or data.get("operation") or fallback.operation_type),
        operation_mode=str(data.get("operation_mode") or data.get("mode") or fallback.operation_mode),
        intent_name=str(data.get("intent_name") or data.get("intent") or fallback.intent_name),
        intent_description=str(data.get("intent_description") or fallback.intent_description),
        patch_text=str(data.get("patch_text") or data.get("content") or fallback.patch_text),
        rationale=str(data.get("rationale") or data.get("reasoning") or fallback.rationale),
        source_sample_ids=list(data.get("source_sample_ids") or fallback.source_sample_ids),
        source_analysis_ids=list(data.get("source_analysis_ids") or fallback.source_analysis_ids),
        risk_level=str(data.get("risk_level") or fallback.risk_level),
        possible_side_effects=list(data.get("possible_side_effects") or fallback.possible_side_effects),
    )
