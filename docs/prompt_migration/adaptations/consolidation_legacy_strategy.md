# Consolidation Legacy Strategy Adaptation

## Source Legacy Prompts

- **CONSOLIDATION_PROMPT** — semantic-preserving compression with hard line budget, logic preservation hierarchy, legal dehydration techniques, reverse-recovery when over-compressed. Inputs: section header + section content. Output: compressed section body. Main capability: merge duplicates, preserve unique constraints, avoid over-compression.
- **CONSOLIDATION_EVAL_PROMPT** — evaluates whether consolidated prompts preserve every unique constraint, placeholder, and output requirement; rejects over-compression ambiguity. Inputs: original section + pruned section. Output: `{"valid": boolean, "reason": string}`. Both `CONSOLIDATION_PROMPT` and `CONSOLIDATION_EVAL_PROMPT` have current LLM-driven targets.

## Current Targets

### LLM_PRUNE_TEMPLATE (`llm_prune`)

- `mmap_optimizer/templates/optimizer_prompts.py::LLM_PRUNE_TEMPLATE` — the compression template that governs how `SemanticCompressionEngine` prunes one section without adding or losing rules.

The original template was minimal:

```
# Role
你压缩一个 prompt section，提高信息密度且不改变含义。

# Section Header
{section_header}

# Section Content
{section_content}

# Rules
- 保留硬约束、边界规则、阈值、占位符、负向提示和有语义作用的示例。
- 删除填充、重复和低价值解释。
- 不得添加原 section 中不存在的规则或事实。
- 输出压缩后的 section body。
```

### LLM_PRUNE_VALIDATION_TEMPLATE (`llm_prune_validation`)

- `mmap_optimizer/templates/optimizer_prompts.py::LLM_PRUNE_VALIDATION_TEMPLATE` — the compression validation template that evaluates semantic equivalence after LLM pruning.

The original template was minimal:

```
# Role
你验证压缩后的 prompt section 是否与原文语义等价。

# Original Section
{original_section}

# Pruned Section
{pruned_section}

# Criteria
- 核心意图、期望模型行为、显式/隐式约束均保留。
- 负向提示、阈值、占位符和输出格式要求均保留。
- 压缩文本未引入新歧义、新规则或安全绕过。

# Output Contract
仅输出 JSON 对象：`{"valid": boolean, "reason": string}`。
```

Both templates are now enriched with legacy strategy rules.

## Migrated Rules

### LLM_PRUNE_TEMPLATE (CONSOLIDATION_PROMPT) — 10 rules

1. **Semantic-Preserving Compression** — 只通过删除冗余、合并等价规则和改进简洁性来压缩。不得删除或削弱业务逻辑、任务约束、示例、输出要求、安全约束或边界条件处理。
2. **Preserve All Unique Constraints** — 每条唯一约束、决策条件、占位符、输出字段、例外和必需行为必须在合并后仍然保留。
3. **Merge Duplicates, Not Differences** — 合并重复或语义等价的规则。不得合并范围、条件、例外、目标 section 或输出要求不同的规则。
4. **Preserve Placeholders and Variables** — 精确保留占位符和插值 token，包括花括号、拼写、大小写以及周围语法。
5. **Preserve Output Contract** — 精确保留所有输出格式要求、模式、标签词汇表、必需字段、JSON 约束和格式化义务。
6. **Preserve Examples and Counterexamples** — 不得删除示例、反例或边界条件，除非它们是完全重复或被等价示例完全包含。
7. **No Over-Compression** — 不得过度压缩，导致结果 prompt 变得歧义、欠明确或更难执行。
8. **Structure-Aware Consolidation** — 尊重 section 边界和层级。优先在同一 section 内合并，再考虑跨 section 合并。
9. **Minimal Wording Changes** — 使用减少冗余所需的最小措辞变更。避免风格重写、任意规范化或新风格。
10. **Output Consolidated Section Only** — 仅输出合并后的 section body。不得包含解释、摘要、Markdown 包装器、在整个 prompt 周围的代码 fence、标签、注释或评注，除非当前契约明确要求。

### LLM_PRUNE_VALIDATION_TEMPLATE (CONSOLIDATION_EVAL_PROMPT) — 4 rules

1. **Evaluate Semantic Preservation** — 评估合并后的 prompt 是否保留了原文中的每条唯一约束、占位符、输出要求、例外和必需行为。
2. **Fail on Semantic Loss** — 如果合并删除了、削弱了、错误合并了或重新解释了任何唯一规则，按现有输出契约标记为失败。
3. **Fail on Over-Compression Ambiguity** — 如果压缩使 prompt 变得歧义、欠明确或更难执行，按现有输出契约标记为失败。
4. **Use Existing Labels Only** — 仅使用现有评估标签/状态。不得引入新标签。

## Rules Not Migrated

- **No output contract changes** — `llm_prune` still outputs section body only; `llm_prune_validation` still outputs `{"valid": boolean, "reason": string}`.
- **No placeholder changes** — `{section_header}`, `{section_content}`, `{original_section}`, `{pruned_section}` preserved.
- **No patch schema changes** — consolidation is not a patch operation generator.
- **No new operations** — consolidation does not introduce patch operations.
- **No new fields** — no new required or optional output fields.
- **No new patch intents** — consolidation purpose remains "compress without semantic loss."
- **No business logic changes** — pure semantic-preserving compression, no rule modification/addition/deletion beyond duplicate merging.
- **No seven-section standardization** — no arbitrary structural reformatting.
- **No arbitrary prompt rewrite** — compression only, no content optimization beyond redundancy removal.
- **No optimizer loop changes** — pure template content only.
- **No patch applier changes** — `PatchApplier` is not touched.
- **No evaluator runtime/parser changes** — evaluator is not affected.
- **No unrelated template changes** — patch_generation, patch_semantic_merge, patch_root_audit, patch_translation, patch_translation_retry, patch_text_match, json_fix, section_rewrite, prompt_format_repair, prompt_numbering_refactor, eval-patch-generation templates are not modified.
- **No direct copy of legacy prompt wholesale** — strategy rules adapted to the current codebase terminology.

## Contract Preservation

| Aspect | Before | After |
| --- | --- | --- |
| `llm_prune` input_variables | `["section_header", "section_content"]` | unchanged |
| `llm_prune` output_contract.type | `"text"` | unchanged |
| `llm_prune` output_contract.fallback | `"original section"` | unchanged |
| `llm_prune` Output format | Compressed section body only, no headers, no code blocks | unchanged |
| `llm_prune_validation` input_variables | `["original_section", "pruned_section"]` | unchanged |
| `llm_prune_validation` output_contract.type | `"json_object"` | unchanged |
| `llm_prune_validation` output fields | `valid: boolean, reason: string` | unchanged |

## Risk

- **Risk level**: medium
- Default behavior only modified through template content; no schema, runtime, optimizer loop, or contract changes.
- The stricter semantic-preserving discipline reduces accidental over-compression and business logic loss; verify on scenario suites before broad adoption.
- **Required follow-up**: run scenario-level A/B to verify shorter prompts without semantic loss.

## Tests

`tests/test_compression_consolidation_legacy_strategy.py` covers:

- **Existence** — both `LLM_PRUNE_TEMPLATE` and `LLM_PRUNE_VALIDATION_TEMPLATE` exist, are non-empty, have required placeholders, no unknown placeholders, mention legacy prompt sources.
- **Contract preservation** — output contracts unchanged; no new required fields; placeholders unchanged; no new operations; no new patch intents.
- **Migrated rule presence** — all 10 llm_prune rules + all 4 llm_prune_validation rules confirmed by phrase-matching.
- **Guardrails** — no business logic changes, no arbitrary standardization, optimizer loop not modified, no Markdown wrappers/fences, no new labels introduced.
- **Other-template isolation** — no patch_generation, patch_semantic_merge, patch_root_audit, patch_translation, json_fix, section_rewrite, prompt_format_repair, prompt_numbering_refactor, eval-patch-generation keywords bleed in.
- **Integration** — module import still works; both specs in registry with correct id/input_variables/output_contract.
