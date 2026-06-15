# Prompt Refactor Legacy Strategy Adaptation

## Source Legacy Prompts

- **PROMPT_REFACTOR_PROMPT** — refactor numbering, ordering markers, list labels, and structural numbering only. Inputs: `{current_prompt}`. Output contract: refactored prompt text only. Main capability: numbering-only refactor with strict semantic preservation and hierarchy discipline.
- **PROMPT_REFACTOR_EVAL_PROMPT** — evaluates refactored prompts for numbering validity and semantic drift. Inputs: `{current_prompt}`, `{refactored_prompt}`. **No current target exists** — the `numbering_refactor` module (`mmap_optimizer/prompt/numbering_refactor.py`) is a pure deterministic text utility that never calls an LLM, so there is no LLM-driven eval prompt to adapt.

## Current Target

- `mmap_optimizer/templates/optimizer_prompts.py::PROMPT_NUMBERING_REFACTOR_TEMPLATE` — the numbering-only refactor template that governs how `prompt_numbering_refactor` utility renumbers Markdown headings, ordered-list markers, and `Step N:` lines.

The original template was minimal:

```text
# Role
你只修复结构化 prompt 的编号。

# Current Prompt
{current_prompt}

# Rules
- 只修改数字/list 编号符号。
- 不得修改措辞、标点、标题层级、顺序或嵌套。
- 不得合并、删除或新增业务规则。
- 仅输出修复后的 prompt body。
```

The new template adds a 10-rule numbering-only refactor discipline framework inherited from the legacy `PROMPT_REFACTOR_PROMPT`.

`PROMPT_REFACTOR_EVAL_PROMPT` is **not migrated** because:
- The `numbering_refactor` module (`mmap_optimizer/prompt/numbering_refactor.py`) is a deterministic, code-level text utility
- It operates without any LLM call, so there is no evaluator prompt to adapt
- Future work may introduce a scenario-gated eval prompt for numbering validity checks

## Migrated Rules

1. **Numbering-Only Refactor** — 只重编编号、排序标记、列表标签和结构编号。不得改变业务逻辑、任务规则、示例、决策标准、输出语义或安全约束。
2. **Preserve Semantic Content** — 精确保留每条原始规则、条件、示例、占位符、变量、输出要求以及例外情况，仅修改必须修复的编号/排序标记。
3. **Fix Duplicate / Skipped / Inconsistent Numbering** — 修复重复编号、跳过编号、不一致的编号样式、损坏的嵌套编号，以及与周围结构不再匹配的列表标签。
4. **Preserve Hierarchy** — 保留原始标题层级和嵌套列表的父子关系。除非当前修复指令明确要求编号更正，否则不得提升、降级、合并、拆分或移动规则。
5. **Preserve Cross-References When Possible** — 如果 prompt 包含交叉引用如"见第 3 步"或"规则 2"，仅更新受编号修复明确影响的引用。不要猜测模糊引用。
6. **Placeholder and Code Block Protection** — 不得修改占位符、变量、代码块、JSON 模式、示例或字面引用的文本，除非编号标记本身在损坏的结构内且必须修复。
7. **Minimal Edit Principle** — 使用恢复一致结构所需的最小可能编号编辑。
8. **No Global Standardization** — 不得将 prompt 规范化为新的风格、七段式结构或任意标准格式。
9. **Ambiguity Fallback** — 如果编号修复需要猜测作者的预期顺序或层级，保留原始文本并避免推测性重排。
10. **Output Refactored Prompt Only** — 只输出修复后的 prompt 文本。不得包含解释、Markdown 包装器、在整个 prompt 周围的代码 fence、标签、注释或评注，除非当前契约明确要求。

## Rules Not Migrated

- **No output contract changes** — still refactored prompt body only, no headers, no code blocks.
- **No placeholder changes** — `{current_prompt}` preserved.
- **No patch schema changes** — numbering refactor is not a patch operation generator.
- **No new operations** — numbering refactor does not introduce patch operations.
- **No new fields** — no new required or optional output fields.
- **No new patch intents** — numbering refactor purpose remains "fix numbering only."
- **No business logic changes** — pure numbering fix, no rule modification/addition/deletion.
- **No seven-section standardization** — no arbitrary structural reformatting.
- **No prompt rewrite / optimization behavior** — numbering fix only, no content optimization.
- **No optimizer loop changes** — pure template content only.
- **No patch applier changes** — `PatchApplier` is not touched.
- **No evaluator runtime/parser changes** — evaluator is not affected.
- **No unrelated template changes** — patch_generation, patch_semantic_merge, patch_root_audit, patch_translation, patch_translation_retry, patch_text_match, json_fix, section_rewrite, prompt_format_repair, eval-patch-generation templates are not modified.
- **No direct copy of legacy prompt wholesale** — strategy rules adapted to the current codebase terminology.
- **PROMPT_REFACTOR_EVAL_PROMPT** — no current target exists (numbering_refactor is a deterministic code utility), not migrated; future scenario-gated work may introduce an eval prompt.

## Contract Preservation

| Aspect | Before | After |
| --- | --- | --- |
| `input_variables` | `["current_prompt"]` | unchanged |
| `output_contract.type` | `"text"` | unchanged |
| `output_contract.fallback` | `"original prompt"` | unchanged |
| Output format | Refactored prompt body only, no headers, no code blocks | unchanged |
| Template role | Fix numbering only, preserving prompt text and structure | unchanged |

## Risk

- **Risk level**: medium-low
- Default behavior only modified through template content; no schema, runtime, optimizer loop, or contract changes.
- The stricter numbering-only discipline prevents accidental semantic drift and business logic changes; verify on scenario suites before broad adoption.
- **Required follow-up**: run scenario-level A/B to verify fewer duplicate/skipped numbering errors without semantic drift.

## Tests

`tests/test_prompt_numbering_refactor_legacy_strategy.py` covers:

- **Existence** — `PROMPT_NUMBERING_REFACTOR_TEMPLATE` exists, is non-empty, has required placeholders, no unknown placeholders, mentions legacy prompt source.
- **Contract preservation** — output is refactored prompt body only; no new required fields; placeholders unchanged; fallback preserved; no new operations; no new patch intents.
- **Migrated rule presence** — all 10 legacy rules confirmed by phrase-matching in template.
- **Guardrails** — no business logic changes, no arbitrary standardization, optimizer loop not modified, no Markdown wrappers/fences, no new placeholders; `PROMPT_REFACTOR_EVAL_PROMPT` migration status documented.
- **Other-template isolation** — no patch_generation, patch_semantic_merge, patch_root_audit, patch_translation, json_fix, section_rewrite, prompt_format_repair, eval-patch-generation keywords bleed in.
- **Integration** — module import still works, `prompt_numbering_refactor` spec in registry with correct id/input_variables/output_contract.

Note: `tests/test_prompt_numbering_refactor_utility.py` tests the deterministic code utility separately and is not modified by this PR.
