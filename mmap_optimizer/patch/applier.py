from __future__ import annotations

from dataclasses import replace

from mmap_optimizer.core.enums import PromptVersionType
from mmap_optimizer.prompt.version import PromptVersion
from .schema import Patch


class PatchApplier:
    def apply(self, base_prompt: PromptVersion, patch: Patch, *, new_version: int) -> PromptVersion:
        section = base_prompt.prompt_ir.section_by_id(patch.section_id)
        if section is None:
            raise ValueError(f"Section not found: {patch.section_id}")
        if patch.operation_mode in {"append", "merge_into_section"}:
            new_content = (section.content.rstrip() + "\n" + patch.patch_text.strip()).strip()
        elif patch.operation_mode == "replace_section":
            new_content = patch.patch_text.strip()
        else:
            new_content = (section.content.rstrip() + "\n" + patch.patch_text.strip()).strip()
        new_ir = base_prompt.prompt_ir.with_replaced_section(patch.section_id, new_content)
        new_ir = replace(new_ir, version=new_version, parent_prompt_ir_id=base_prompt.prompt_ir.id, applied_patch_ids=[*base_prompt.prompt_ir.applied_patch_ids, patch.id])
        prompt_type_value = getattr(base_prompt.prompt_type, "value", str(base_prompt.prompt_type))
        new_prompt = PromptVersion(
            id=f"{prompt_type_value}_prompt_v{new_version}", prompt_type=base_prompt.prompt_type, version=new_version,
            prompt_ir=new_ir, output_schema_contract_id=base_prompt.output_schema_contract_id,
            version_type=PromptVersionType.OPTIMIZATION, parent_version_id=base_prompt.id,
            applied_patch_ids=[*base_prompt.applied_patch_ids, patch.id],
        )
        new_prompt.render()
        return new_prompt
