from __future__ import annotations

from .registry import PromptTemplateRegistry
from .schema import PromptTemplateSpec

PATCH_TEXT_MATCH_TEMPLATE = """# Role
You are a strict prompt text-alignment specialist.

# Source Section
{section_content}

# Intent Text
{intent_text}

# Field Type
{field_type}

# Rules
- Return only one verbatim contiguous substring from Source Section.
- Never rewrite, summarize, translate, or add characters.
- Match only inside the provided Source Section.
- If no semantically close substring exists, return an empty response.
"""

PATCH_TRANSLATION_TEMPLATE = """# Role
You calibrate patch locator fields against the actual prompt while preserving payload fields.

# Prompt Structure
{prompt_structure}

# Current Prompt
{current_prompt}

# Patches To Align
{patches_json}

# Rules
- You may change only target_section, section_id, old_text, and target_text.
- Preserve op, operation_mode, content, patch_text, new_text, new_content, rationale, and reasoning exactly.
- Align old_text and target_text only within the selected section.
- Keep every input patch; do not drop or invent patches.
- If a locator cannot be aligned, leave that locator unchanged.

# Output
Return only a JSON array of aligned patches.
"""

PATCH_TRANSLATION_RETRY_TEMPLATE = """# Role
You repair one failed patch locator after an apply failure.

# Failure Details
{failure_info}

# Prompt Structure
{prompt_structure}

# Current Prompt
{current_prompt}

# Failed Patch
{patch_json}

# Rules
- Output a JSON array with exactly one patch.
- You may change only target_section, section_id, old_text, and target_text.
- Payload and reasoning fields must remain byte-for-byte identical.
- If no exact in-section alignment is possible, return the original patch unchanged.
"""

JSON_FIX_TEMPLATE = """# Role
You repair polluted or malformed JSON without changing core key/value content.

# Raw Text
{raw_text}

# Rules
- Strip chatty prefixes, suffixes, and markdown fences.
- Repair only JSON syntax such as missing brackets, commas, or escaping.
- Do not invent, delete, or reinterpret core fields.
- Return only valid JSON whose first character is {{ or [.
"""

PATCH_SEMANTIC_MERGE_TEMPLATE = """# Role
You merge related prompt patches into a concise, conflict-free patch list.

# Prompt Structure
{prompt_structure}

# Patches
{patches_json}

# Rules
- Group by target section; do not mix unrelated sections.
- Preserve unique boundary-case intent unless it conflicts with higher-priority rules.
- Generalize repeated failures into specific reusable rules.
- Prefer append-style changes unless existing text must be corrected exactly.
- Do not edit frozen/schema sections.

# Output
Return only a JSON array of merged patch candidates.
"""

PATCH_ROOT_AUDIT_TEMPLATE = """# Role
You audit final prompt patches for cross-section conflicts and redundancy.

# Prompt Structure
{prompt_structure}

# Patches
{patches_json}

# Audit Checks
- Rules must not contradict Output Format or frozen schemas.
- Workflow changes must not bypass constraints or self-checks.
- Remove duplicate intent only when the remaining section is clearly the better home.
- Preserve independent non-conflicting boundary-case patches.
- Do not invent unrelated new patch intent.

# Output
Return only a JSON array of audited patch candidates.
"""

SECTION_REWRITE_TEMPLATE = """# Role
You rewrite one prompt section without losing existing rules.

# Section Header
{section_header}

# Current Section
{section_content}

# Optimization Instruction
{optimization_instruction}

# Rules
- Preserve all core constraints, business rules, placeholders, and negative instructions.
- Integrate the optimization instruction only when it is compatible with existing intent.
- Improve organization and concision without adding unrelated rules.
- Output section body only; do not include the section header or commentary.
"""

LLM_PRUNE_TEMPLATE = """# Role
You prune one prompt section for density while preserving meaning.

# Section Header
{section_header}

# Section Content
{section_content}

# Rules
- Preserve hard constraints, boundaries, placeholders, examples with semantic force, and section purpose.
- Remove filler, repetition, and low-value explanation.
- Do not add rules or facts absent from the original section.
- Output only the pruned section body.
"""

LLM_PRUNE_VALIDATION_TEMPLATE = """# Role
You validate whether a pruned prompt section preserves original semantics.

# Original Section
{original_section}

# Pruned Section
{pruned_section}

# Criteria
- Core intent and expected model behavior are preserved.
- Explicit and implicit constraints, negative instructions, thresholds, and placeholders are preserved.
- The pruned text introduces no ambiguity or new rule.

# Output
Return only JSON: {{"valid": true, "reason": "..."}} or {{"valid": false, "reason": "..."}}.
"""

PROMPT_NUMBERING_REFACTOR_TEMPLATE = """# Role
You fix numbering in a structured prompt.

# Current Prompt
{current_prompt}

# Rules
- Change only numeric/list numbering markers.
- Do not change wording, punctuation, heading levels, order, or nesting.
- Do not merge, delete, or add business rules.
- Output only the repaired prompt body.
"""

PROMPT_FORMAT_REPAIR_TEMPLATE = """# Role
You normalize prompt formatting without changing content semantics.

# Issues
{issues_description}

# Original Prompt
{original_prompt}

# Rules
- Preserve every business rule and judgment condition.
- Only normalize headings, spacing, and list structure.
- Do not invent role, constraints, examples, or output fields.
- Keep information order unless moving output-format text into an output-format section is explicitly required.
- Output only the normalized prompt.
"""

PROMPT_STANDARDIZATION_TEMPLATE = """# Role
You map a raw prompt into a standard section structure without changing business logic.

# Original Prompt
{original_prompt}

# Target Sections
1. Task Description
2. Core Instructions
3. Step-by-Step Reasoning Process
4. Constraints & Rules
5. Output Format
6. Examples
7. Additional Guidelines

# Rules
- Preserve all original requirements exactly in meaning.
- Do not invent missing role, examples, or supplemental guidance.
- Use empty sections only when configured by the caller; otherwise omit absent sections.
- Output only standardized markdown.
"""

DEFAULT_OPTIMIZER_TEMPLATES = [
    PromptTemplateSpec("patch_text_match", "1.0", "Map fuzzy locator text to a verbatim in-section substring.", ["section_content", "intent_text", "field_type"], {"type": "text_or_empty"}, PATCH_TEXT_MATCH_TEMPLATE, "low", ["patch", "alignment"]),
    PromptTemplateSpec("patch_translation", "1.0", "Calibrate legacy/free-form patch locator fields while preserving payload.", ["prompt_structure", "current_prompt", "patches_json"], {"type": "json_array"}, PATCH_TRANSLATION_TEMPLATE, "medium", ["patch", "alignment"]),
    PromptTemplateSpec("patch_translation_retry", "1.0", "Retry one failed patch locator calibration using apply failure details.", ["failure_info", "prompt_structure", "current_prompt", "patch_json"], {"type": "json_array", "items": 1}, PATCH_TRANSLATION_RETRY_TEMPLATE, "medium", ["patch", "alignment"]),
    PromptTemplateSpec("json_fix", "1.0", "Repair polluted or malformed JSON after deterministic repair fails.", ["raw_text"], {"type": "json"}, JSON_FIX_TEMPLATE, "medium", ["analysis", "repair"]),
    PromptTemplateSpec("patch_semantic_merge", "1.0", "Generalize and merge related patch candidates before strict validation.", ["prompt_structure", "patches_json"], {"type": "json_array"}, PATCH_SEMANTIC_MERGE_TEMPLATE, "high", ["patch", "merge"]),
    PromptTemplateSpec("patch_root_audit", "1.0", "Audit final patch candidates for cross-section conflicts.", ["prompt_structure", "patches_json"], {"type": "json_array"}, PATCH_ROOT_AUDIT_TEMPLATE, "high", ["patch", "merge"]),
    PromptTemplateSpec("section_rewrite", "1.0", "Rewrite a single section while preserving existing rule intent.", ["section_header", "section_content", "optimization_instruction"], {"type": "text"}, SECTION_REWRITE_TEMPLATE, "high", ["patch", "rewrite"]),
    PromptTemplateSpec("llm_prune", "1.0", "Prune one section without adding or losing rules.", ["section_header", "section_content"], {"type": "text"}, LLM_PRUNE_TEMPLATE, "high", ["compression"]),
    PromptTemplateSpec("llm_prune_validation", "1.0", "Validate semantic equivalence after LLM pruning.", ["original_section", "pruned_section"], {"type": "json_object"}, LLM_PRUNE_VALIDATION_TEMPLATE, "medium", ["compression", "validation"]),
    PromptTemplateSpec("prompt_numbering_refactor", "1.0", "Fix numbering only, preserving prompt text and structure.", ["current_prompt"], {"type": "text"}, PROMPT_NUMBERING_REFACTOR_TEMPLATE, "low", ["prompt", "format"]),
    PromptTemplateSpec("prompt_format_repair", "1.0", "Normalize prompt formatting without semantic changes.", ["issues_description", "original_prompt"], {"type": "text"}, PROMPT_FORMAT_REPAIR_TEMPLATE, "medium", ["prompt", "format"]),
    PromptTemplateSpec("prompt_standardization", "1.0", "Map raw prompt content into a standard section structure losslessly.", ["original_prompt"], {"type": "text"}, PROMPT_STANDARDIZATION_TEMPLATE, "medium", ["prompt", "format"]),
]


def build_default_template_registry() -> PromptTemplateRegistry:
    registry = PromptTemplateRegistry()
    for template in DEFAULT_OPTIMIZER_TEMPLATES:
        registry.register(template)
    return registry
