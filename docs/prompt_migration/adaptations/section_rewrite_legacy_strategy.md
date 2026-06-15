# Section Rewrite Legacy Strategy Adaptation

## Source Legacy Prompt

- **PROMPT_REPLACE_SECTION_TEMPLATE** — targeted section-level rewrite with optimization instructions. Inputs: `{section_header}`, `{section_content}`, `{optimization_instruction}`. Output contract: raw section text only — no headers, no code blocks, no preamble. Main capability: incremental fusion section rewriting with logic reorganization without replacement, tone/style consistency, no header / no preamble / raw section only.

## Current Target

- `mmap_optimizer/templates/optimizer_prompts.py::SECTION_REWRITE_TEMPLATE` — the section rewrite template used for rewriting a single prompt section while preserving existing rule intent.

The original template was minimal:
```
# Role
你重写单个 prompt section，但必须无损保留已有规则。

# Section Header
{section_header}

# Current Section
{section_content}

# Optimization Instruction
{optimization_instruction}

# Rules
- 保留全部核心约束、业务规则、占位符、负向提示和输出要求。
- 只融合兼容的优化指令；不得添加无关规则。
- 提升结构和简洁度，但不能改变语义。
- 输出 section body；不要包含 header、解释或 Markdown fence。
```

The new template adds a 10-rule section rewrite discipline framework inherited from the legacy prompt.

## Migrated Rules

1. **Target-Section-Only Rewrite** — 只重写指定的目标 section。不得修改、重排、总结、删除或添加任何其他 section 的内容。
2. **Preserve Section Boundary** — 保持目标 section 的边界和标题语义。重写后的内容必须保持在同一 section 身份内。当前输出契约要求只输出 section body，不输出 heading。
3. **Preserve Placeholders and Variables** — 保持所有现有占位符、变量、格式标记和必需插值字段，除非请求的变更明确针对它们。示例：{section_header} {section_content} {optimization_instruction} 以及原 section 中已有的任何占位符。
4. **Minimal Rewrite Principle** — 执行满足请求变更的最小重写。避免广泛的风格重写、无关澄清或全局规范化。
5. **Preserve Unrelated Constraints** — 保留原 section 中所有无关约束、示例、安全规则、输出格式要求和决策条件。
6. **No Semantic Drift** — 不得改变未被请求编辑直接针对的规则的预期含义。
7. **No Section Creation or Deletion** — 不得创建新 section、删除 section、合并 section、拆分 section 或在 section 之间移动规则。
8. **Output Contract Strictness** — 严格返回当前要求的输出格式：仅输出 section body，不包含 Markdown、解释、代码 fence、标签或注释。
9. **Failure / Ambiguity Fallback** — 如果请求的重写无法在不违反 section 边界、占位符或输出契约的情况下安全应用，保持原 section 内容或使用当前 fallback 行为。不要猜测。
10. **Patch-Intent Fidelity** — 重写必须仅实现请求的 patch intent。不得添加额外改进或未来预防规则。

## Rules Not Migrated

- **No output contract changes** — still raw section text only, no headers, no code blocks.
- **No placeholder changes** — {section_header}, {section_content}, {optimization_instruction} preserved.
- **No patch schema changes** — section rewrite is not a patch operation generator.
- **No new operations** — section rewrite does not introduce patch operations.
- **No new fields** — no new required or optional output fields.
- **No new patch intents** — section rewrite purpose remains "rewrite single section".
- **No cross-section edits** — only target section may be modified.
- **No section creation/deletion** — only rewrite, not create/delete/merge/split.
- **No optimizer loop changes** — pure template content only.
- **No patch applier changes** — PatchApplier is not touched.
- **No evaluator runtime/parser changes** — evaluator is not affected.
- **No unrelated template changes** — patch_generation, patch_semantic_merge, patch_root_audit, patch_translation, patch_translation_retry, patch_text_match, json_fix, eval-patch-generation, compression templates are not modified.
- **No direct copy of legacy prompt wholesale** — strategy rules adapted to current codebase terminology.

## Contract Preservation

| Aspect | Before | After |
| --- | --- | --- |
| `input_variables` | `["section_header", "section_content", "optimization_instruction"]` | unchanged |
| `output_contract.type` | `"text"` | unchanged |
| `output_contract.fallback` | `"original section"` | unchanged |
| Output format | Raw section body only, no headers, no code blocks | unchanged |
| Template role | Rewrite single section while preserving existing rule intent | unchanged |

## Risk

- **Risk level**: medium-low
- Default behavior only modified through template content; no schema, runtime, optimizer loop, or contract changes.
- The stricter section-local rewrite discipline reduces cross-section edits and broad global rewrites; verify on scenario suites before broad adoption.
- **Required follow-up**: run scenario-level A/B to verify fewer cross-section edits and better section-local rewrite fidelity.

## Tests

`tests/test_optimizer_prompt_section_rewrite_template.py` covers:

- **Existence** — `SECTION_REWRITE_TEMPLATE` exists, is non-empty, has required placeholders, no unknown placeholders, mentions legacy prompt source.
- **Contract preservation** — output contract is text-only, no new required fields, placeholders unchanged, fallback behavior preserved, no new operations, no new patch intents.
- **Migrated rule presence** — all 10 legacy rules confirmed by phrase-matching in template.
- **Guardrails** — no cross-section edits, no section creation/deletion, no broad global rewrite, optimizer loop not modified, no Markdown/fences in output, output is section body only.
- **Other-template isolation** — no patch_generation, patch_semantic_merge, patch_root_audit, patch_translation, json_fix, eval-patch-generation, compression keywords bleed in.
- **Integration** — module import still works, section_rewrite spec in registry with correct id/input_variables/output_contract, template non-trivial.