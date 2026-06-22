from __future__ import annotations

import logging
import time
from dataclasses import replace

from mmap_optimizer.core.enums import PromptVersionType
from mmap_optimizer.logging import get_logger, log_stage
from mmap_optimizer.prompt.version import PromptVersion
from .schema import Patch

logger = get_logger(__name__)


class PatchApplyError(ValueError):
    """Raised when a patch cannot be applied exactly."""


class PatchApplier:
    def apply(
        self,
        base_prompt: PromptVersion,
        patch: Patch,
        *,
        new_version: int,
        version_type: PromptVersionType | str = PromptVersionType.OPTIMIZATION,
        round_id: str | None = None,
        run_id: str | None = None,
    ) -> PromptVersion:
        apply_start_time = time.perf_counter()
        section = base_prompt.prompt_ir.section_by_id(patch.section_id)
        if section is None:
            raise PatchApplyError(f"Section not found: {patch.section_id}")
        if section.mutability == "frozen":
            raise PatchApplyError(f"Cannot patch frozen section: {patch.section_id}")
        mode = patch.effective_operation_mode
        if mode in {"append", "merge_into_section"}:
            new_content = (section.content.rstrip() + "\n" + patch.patch_text.strip()).strip()
        elif mode == "replace_section":
            new_content = patch.patch_text.strip()
        elif mode == "replace_in_section":
            old_text = patch.locator_value("old_text")
            new_text = patch.payload_value("new_text") or patch.new_text or patch.patch_text
            if not old_text or old_text not in section.content:
                raise PatchApplyError(f"Patch locator not found for replace_in_section: {patch.id}")
            occurrences = section.content.count(old_text)
            if occurrences > 1:
                raise PatchApplyError(f"Ambiguous locator for replace_in_section: {old_text!r} appears {occurrences} times")
            new_content = section.content.replace(old_text, new_text, 1)
        elif mode == "insert_after":
            target_text = patch.locator_value("target_text")
            insert_text = patch.payload_value("insert_text") or patch.insert_text or patch.patch_text
            if not target_text or target_text not in section.content:
                raise PatchApplyError(f"Patch locator not found for insert_after: {patch.id}")
            occurrences = section.content.count(target_text)
            if occurrences > 1:
                raise PatchApplyError(f"Ambiguous locator for insert_after: {target_text!r} appears {occurrences} times")
            new_content = section.content.replace(target_text, target_text + "\n" + insert_text.strip(), 1)
        elif mode == "insert_before":
            target_text = patch.locator_value("target_text")
            insert_text = patch.payload_value("insert_text") or patch.insert_text or patch.patch_text
            if not target_text or target_text not in section.content:
                raise PatchApplyError(f"Patch locator not found for insert_before: {patch.id}")
            occurrences = section.content.count(target_text)
            if occurrences > 1:
                raise PatchApplyError(f"Ambiguous locator for insert_before: {target_text!r} appears {occurrences} times")
            new_content = section.content.replace(target_text, insert_text.strip() + "\n" + target_text, 1)
        elif mode == "delete":
            target_text = patch.locator_value("old_text") or patch.locator_value("target_text")
            if not target_text or target_text not in section.content:
                raise PatchApplyError(f"Patch locator not found for delete: {patch.id}")
            occurrences = section.content.count(target_text)
            if occurrences > 1:
                raise PatchApplyError(f"Ambiguous locator for delete: {target_text!r} appears {occurrences} times")
            new_content = section.content.replace(target_text, "", 1)
        else:
            new_content = (section.content.rstrip() + "\n" + patch.patch_text.strip()).strip()
        new_ir = base_prompt.prompt_ir.with_replaced_section(patch.section_id, new_content)
        new_ir = replace(new_ir, version=new_version, parent_prompt_ir_id=base_prompt.prompt_ir.id, applied_patch_ids=[*base_prompt.prompt_ir.applied_patch_ids, patch.id])
        prompt_type_value = getattr(base_prompt.prompt_type, "value", str(base_prompt.prompt_type))
        new_prompt = PromptVersion(
            id=f"{prompt_type_value}_prompt_v{new_version}", prompt_type=base_prompt.prompt_type, version=new_version,
            prompt_ir=new_ir, output_schema_contract_id=base_prompt.output_schema_contract_id,
            version_type=version_type, parent_version_id=base_prompt.id,
            applied_patch_ids=[*base_prompt.applied_patch_ids, patch.id],
            created_by_round_id=round_id,
            created_by_run_id=run_id,
        )
        new_prompt.render()
        apply_duration_ms = int((time.perf_counter() - apply_start_time) * 1000)
        log_stage(logger, "patch_apply", "补丁应用完成", patch_id=patch.id, section_id=patch.section_id, mode=mode, duration_ms=apply_duration_ms)
        return new_prompt
