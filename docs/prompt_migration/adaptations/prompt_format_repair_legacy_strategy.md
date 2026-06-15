# Prompt Format Repair Legacy Strategy Adaptation

## Source Legacy Prompt

- **PROMPT_FORMAT_REPAIR_PROMPT** — repair malformed prompt formatting while preserving semantic content. Inputs: `{issues_description}`, `{original_prompt}`. Output contract: repaired prompt text only. Main capability: format-only repair with strict placeholder and output-contract preservation.

## Current Target

- `mmap_optimizer/templates/optimizer_prompts.py::PROMPT_FORMAT_REPAIR_TEMPLATE` — the prompt format repair template used for normalizing prompt formatting without semantic changes.

The original template was minimal:

```text
# Role
你规范化 prompt 格式，但不改变语义。

# Issues
{issues_description}

# Original Prompt
{original_prompt}

# Rules
- 保留每条业务规则和判断条件。
- 只规范标题、空行和列表结构。
- 不得发明角色、约束、示例或输出字段。
- 除非明确要求整理输出格式 section，否则保持信息顺序。
- 仅输出规范化后的 prompt。
```

The new template adds a 10-rule format-only repair discipline framework inherited from the legacy prompt.

## Migrated Rules

1. **Format-Only Repair** — 只修复格式。不得改变业务逻辑、任务规则、示例、决策标准、输出语义或安全约束。
2. **Preserve All Semantic Content** — 保留每条原始规则、条件、示例、占位符、变量、输出要求以及例外情况，除非当前修复指令明确针对其周围的格式。
3. **Markdown Structure Repair** — 修复格式错误的 Markdown 标题层级、列表缩进、项目符号一致性、代码 fence 边界、表格对齐、空格、以及 section 分隔。
4. **No Section Semantic Drift** — 不得在改变含义的情况下跨 section 移动内容。如果某行由于损坏的格式明显属于邻近 section，最小化修复位置并保留措辞。
5. **Placeholder Preservation** — 精确保留占位符和插值 token，包括花括号、拼写、大小写以及周围语法。
6. **Output Contract Preservation** — 精确保留 prompt 的输出格式要求。不得添加、删除或重新解释输出字段、JSON 模式、标签词汇表或决策格式。
7. **Minimal Edit Principle** — 使用恢复可读性和结构有效性所需的最小可能的格式编辑。
8. **No Global Standardization** — 不得将 prompt 规范化为新的风格、七段式结构或任意标准格式，除非当前修复指令明确要求。
9. **Ambiguity Fallback** — 如果格式修复需要猜测作者意图，保留原始文本并避免推测性重排。
10. **Output Repaired Prompt Only** — 只输出修复后的 prompt 文本。不得包含解释、Markdown 包装器、在整个 prompt 周围的代码 fence、标签、注释或评注，除非当前契约明确要求。

## Rules Not Migrated

- **No output contract changes** — still raw repaired prompt text only.
- **No placeholder changes** — `{issues_description}` and `{original_prompt}` preserved.
- **No patch schema changes** — format repair is not a patch operation generator.
- **No new operations** — format repair does not introduce patch operations.
- **No new fields** — no new required or optional output fields.
- **No new patch intents** — format repair purpose remains "format normalization."
- **No business logic changes** — pure formatting, no rule modification/addition/deletion.
- **No seven-section standardization** — no arbitrary structural reformatting.
- **No prompt rewrite / optimization behavior** — format repair only, no content optimization.
- **No optimizer loop changes** — pure template content only.
- **No patch applier changes** — `PatchApplier` is not touched.
- **No evaluator runtime/parser changes** — evaluator is not affected.
- **No unrelated template changes** — patch_generation, patch_semantic_merge, patch_root_audit, patch_translation, patch_translation_retry, patch_text_match, json_fix, section_rewrite, eval-patch-generation templates are not modified.
- **No direct copy of legacy prompt wholesale** — strategy rules adapted to the current codebase terminology.

## Contract Preservation

| Aspect | Before | After |
| --- | --- | --- |
| `input_variables` | `["issues_description", "original_prompt"]` | unchanged |
| `output_contract.type` | `"text"` | unchanged |
| Output format | Raw repaired prompt text only | unchanged |
| Template role | Normalize prompt formatting without semantic changes | unchanged |

## Risk

- **Risk level**: medium-low
- Default behavior only modified through template content; no schema, runtime, optimizer loop, or contract changes.
- The stricter format-only discipline prevents accidental semantic drift and business logic changes; verify on scenario suites before broad adoption.
- **Required follow-up**: run scenario-level A/B to verify fewer malformed Markdown / placeholder / section-boundary errors.

## Tests

`tests/test_optimizer_prompt_format_repair_template.py` covers:

- **Existence** — `PROMPT_FORMAT_REPAIR_TEMPLATE` exists, is non-empty, has required placeholders, no unknown placeholders, mentions legacy prompt source.
- **Contract preservation** — output is repaired prompt text only; no new required fields; placeholders unchanged; fallback preserved; no new operations; no new patch intents.
- **Migrated rule presence** — all 10 legacy rules confirmed by phrase-matching in template.
- **Guardrails** — no business logic changes, no arbitrary standardization, optimizer loop not modified, no Markdown wrappers/fences, no new placeholders.
- **Other-template isolation** — no patch_generation, patch_semantic_merge, patch_root_audit, patch_translation, json_fix, section_rewrite, eval-patch-generation keywords bleed in.
- **Integration** — module import still works, prompt_format_repair spec in registry with correct id/input_variables/output_contract.
