from __future__ import annotations

ANALYSIS_OUTPUT_REQUIRED_FIELDS = [
    "judgement",
    "confirmed_facts",
    "hypothesized_error_causes",
    "prompt_section_attribution",
    "patch_candidates",
]

PATCH_CANDIDATE_REQUIRED_FIELDS = [
    "target_prompt",
    "target_section",
    "operation",
    "intent",
    "content",
    "risk",
]

ANALYSIS_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ANALYSIS_OUTPUT_REQUIRED_FIELDS,
    "properties": {
        "judgement": {"type": "object"},
        "confirmed_facts": {"type": "array"},
        "hypothesized_error_causes": {"type": "array"},
        "prompt_section_attribution": {"type": "array"},
        "patch_candidates": {"type": "array"},
    },
}
