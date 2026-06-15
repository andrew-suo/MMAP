from __future__ import annotations

from .registry import PromptTemplateRegistry
from .schema import PromptTemplateSpec

PATCH_TEXT_MATCH_TEMPLATE = """# Role
你是极其严谨的 Prompt 文本定位与对齐专家。
本模板继承自 legacy PATCH_TEXT_MATCH_PROMPT 规则，只做 substring 匹配，不生成、不合并、不审计、不改写文本。

# Source Section
{section_content}

# Intent Text
{intent_text}

# Field Type
{field_type}

# Legacy PATCH_TEXT_MATCH_PROMPT Matching Framework

## 1. Pure Substring Extraction
Return only the matched substring copied from the provided section content.
Do not output explanations, JSON, Markdown, code fences, quotes, labels, or
commentary. The output must be a raw substring only — nothing else.

## 2. De-Paraphrasing from Intent Text to Source Text
The intent_text may be paraphrased, summarized, or semantically similar to
the source text. Resolve it back to the exact source substring that appears
verbatim in section_content. Intent text is only a semantic hint; the output
must always come from the source.

## 3. Longest Meaningful Substring Rule
When multiple candidates match, choose the longest meaningful substring that
fully captures the intended edit target without including unrelated
neighboring instructions. Prefer the longest meaningful substring that is
still a clean, contiguous piece of source text.

## 4. Exact Source-Copy Requirement
The output must be copied verbatim from section_content, preserving original
wording, punctuation, and whitespace where relevant. Never rephrase,
re-punctuate, or normalize the matched substring.

## 5. In-Section Only
Search only within the provided section_content. Do not infer or import text
from other prompt sections. Do not combine fragments from outside the
provided section.

## 6. Total Fuse on No Reliable Match
If no reliable source substring can be found, return an empty string. Do not
guess, paraphrase, synthesize, or repair text. Do not fall back to the
intent_text or any invented substitute.

## 7. Field-Type Sensitivity
Use field_type only to understand what kind of locator is being matched —
such as old_text, target_text, or insertion anchor. Do not let field_type
change the output contract or the shape of what you return.

## 8. No Semantic Rewriting
This task is text matching only. Do not rewrite the prompt, generate a
patch, merge patches, audit patches, or improve wording.

## 9. No Hallucinated Source Text
Never output text that is not present verbatim in section_content.

# Rules
- 仅在 Source Section 内查找，不得跨 section。
- 优先 100% 精确匹配；精确失败后才进入模糊匹配。
- 模糊匹配必须返回 Source Section 中原样存在、连续不断的最长可信子串。
- 严禁臆造、改写、翻译、补字或删除字符。
- 若相似度低于阈值或无法确认，输出空字符串。

# Migration Note
This template has been enriched with the verbatim substring matching and
de-paraphrasing framework inherited from the legacy PATCH_TEXT_MATCH_PROMPT.
- The current output contract, placeholders, and contract type remain unchanged.
- No new placeholders are introduced.
- No new patch operations, required fields, or brand-new patch intents are introduced.
- Output remains a plain matched substring — not JSON, not Markdown, not explanation,
  not a patch, not a translation, not a merge, not an audit.
- Patch text match remains a pure substring extraction layer only.

# Output Contract
仅输出匹配到的原文子串；无匹配时输出零字符空响应。
"""

PATCH_TRANSLATION_TEMPLATE = """# Role
你是 Patch 文本校准专家。你需要将 patch locator 字段对齐到当前 Prompt 原文，同时保护 payload 不被篡改。
本模板继承自 legacy PATCH_TRANSLATION_PROMPT 规则，只做 locator 校准，不生成、不合并、不审计 patch 内容。

# Prompt Structure
{prompt_structure}

# Current Prompt
{current_prompt}

# Patches To Align
{patches_json}

# Legacy PATCH_TRANSLATION_PROMPT Locator Calibration Framework

## 1. Exact Section Header Calibration
Map any fuzzy or paraphrased target section reference to the exact section
header string that exists in the current prompt structure. Do not invent
section names. `target_section` / `section_id` must be one of the headers
listed in the provided prompt structure.

## 2. In-Section-Only Locator Matching
After the section is calibrated, search only inside that section for
`old_text` / `target_text`. Do not search across unrelated sections.
Strictly match within the boundary of the calibrated section.

## 3. Payload Immutability
Only locator fields may be corrected. Preserve the original patch payload,
operation, reasoning, new_text, and risk metadata exactly. Do not modify
`op`, `operation_mode`, `content`, `patch_text`, `new_text`, `new_content`,
`rationale`, `reasoning`, or any semantic payload field. Only locator-related
fields may be changed. Preserve all non-locator payload exactly.

## 4. N-in-N-out Count Preservation
Return exactly the same number of patch objects as received. Do not add,
delete, split, or merge patches during translation. The same number of
patches — N-in-N-out — must be preserved.

## 5. Verbatim Locator Requirement
The translated `old_text` / `target_text` must be copied verbatim from
the current prompt, including punctuation and whitespace where relevant.
Never paraphrase or approximate locator text.

## 6. Zero-Hallucination Fuse — Unresolved Locator Fallback
If no reliable section or text match can be found, keep the patch unchanged
and mark the locator as unresolved using `extra.unresolved_locators`. Do not
guess approximate source text. Never invent content that does not exist in
the provided prompt structure or current prompt text.

## 7. No Semantic Rewriting
Patch translation is not patch generation, not merge, and not root audit.
Do not rewrite patch intent, add rules, or improve content while calibrating
locators. Your only action is locator field correction — no semantic rewriting.

# Calibration Workflow
1. 校准 section header：`target_section` / `section_id` 必须指向 Prompt Structure 中真实存在的 section。
2. 在该 section 范围内硬匹配 `old_text` / `target_text`；精确失败后才允许模糊匹配。
3. 模糊匹配需给出高相似度、最长可信连续原文；低于阈值时不得替换。
4. 找不到时保持原 locator，并在 `extra.unresolved_locators` 标记字段名。

# Zero-Hallucination Rules
- 不要臆造当前 prompt 中不存在的文本。
- 不要添加原 prompt 中不存在的规则或约束。
- 只可修改 `target_section`, `section_id`, `old_text`, `target_text`, `extra.unresolved_locators`。
- `op`, `operation_mode`, `content`, `patch_text`, `new_text`, `new_content`, `rationale`, `reasoning` 必须逐字保持不变。
- 输入多少 patch，输出多少 patch，不得丢弃。

# Migration Note
This template has been enriched with the locator calibration framework
inherited from the legacy PATCH_TRANSLATION_PROMPT.
- The current patch JSON schema, placeholders, and operation list remain unchanged.
- No new patch operations, required fields, or brand-new patch intents are introduced.
- N-in-N-out count is strictly preserved; no add / delete / split / merge during translation.
- Patch translation remains a locator calibration layer only — not patch
  generation, not patch merge, not root audit.

# Output Contract
返回 JSON 数组。每个元素仍为 patch 对象；无法对齐时保留原值并写入 `extra.unresolved_locators`。
"""

PATCH_TRANSLATION_RETRY_TEMPLATE = """# Role
你是 Patch 二次校准与故障修复专家。上一次 apply/validate 因 locator 匹配失败被拦截，你必须根据失败原因做一次保守修复。
本模板继承自 legacy PATCH_TRANSLATION_RETRY_PROMPT 规则，只做 locator 修复，不生成、不合并、不审计 patch 内容。

# Failure Details
{failure_info}

# Prompt Structure
{prompt_structure}

# Current Prompt
{current_prompt}

# Failed Patch
{patch_json}

# Legacy PATCH_TRANSLATION_RETRY_PROMPT Retry Framework

## 1. Failure-Info Driven Retry
Use failure_info as the primary signal. Fix only the locator problem
described by the failure; do not re-interpret the entire patch. If
`failure_info` references a specific section, target text, or locator
field name, address exactly that issue.

## 2. Exactly-One Retry Output
Return exactly one-element JSON array; the single patch must be the
repaired version of the input patch. Do not output multiple alternatives.
Do not add, delete, or split patches.

## 3. Header → In-Section Hard Match → Fuse Order
Retry strictly in this order:
1. Calibrate the exact section header: choose a section id/header that
   is 100% present in the provided prompt structure.
2. Search for exact in-section `old_text` / `target_text` — return the
   verbatim current-prompt text, including punctuation and whitespace.
3. If exact match fails, use the safest supported unresolved fallback:
   preserve the original patch and mark unresolved locators via
   `extra.unresolved_locators`.

## 4. No Guessing
Do not guess approximate source text. If no reliable match exists,
preserve the original patch and surface unresolved locator information
according to the current schema. Never paraphrase or fabricate locator
content.

## 5. Preserve All Non-Locator Payload
The retry may only repair locator-related fields. Only locator-related
fields may be changed. Preserve all non-locator payload exactly. It must
not modify operation, intended new_text, reasoning, risk, or any other
semantic payload. Only `target_section`, `section_id`, `old_text`,
`target_text`, and `extra.unresolved_locators` may change.

# Required Steps
1. 定位并校准 section header：必须选择 Prompt Structure 中 100% 存在的 section id/header。
2. 在该 section 内硬匹配 `old_text` / `target_text`，返回逐字逐标点的原文。
3. 若精确匹配失败，可模糊匹配；必须选择最长可信片段，并拒绝低相似度候选。
4. 如果仍无法匹配，原样返回 patch，并在 `extra.unresolved_locators` 标记 unresolved 字段，交由人工处理。

# Guardrails
- 零幻觉：绝不臆造当前 prompt 中不存在的文本。
- Payload 锁定：除 locator 与 `extra.unresolved_locators` 外，其他字段必须逐字不变。
- 输出数组必须有且仅有一个 patch。

# Migration Note
This template has been enriched with the failure-driven retry framework
inherited from the legacy PATCH_TRANSLATION_RETRY_PROMPT.
- The current patch JSON schema, placeholders, and operation list remain unchanged.
- No new patch operations, required fields, or brand-new patch intents are introduced.
- Patch translation retry remains a locator calibration layer only — not
  patch generation, not patch merge, not root audit.
- Exactly-one-patch one-element JSON array output is strictly enforced.

# Output Contract
返回 JSON 数组：`[patch]`。patch 必须符合原 patch schema；错误情况下使用原 patch + `extra.unresolved_locators` fallback。
"""

JSON_FIX_TEMPLATE = """# Role
你是 JSON 数据清洗与结构化修复专家。
本模板继承自 legacy JSON_FIX_PROMPT 规则，只做语法修复，不执行业务推理、不生成新内容、不改语义。

# Legacy JSON_FIX_PROMPT Repair Framework

## 1. Syntax-Only Repair
Repair only JSON syntax, escaping, brackets, commas, quotes, and structural
validity. Do not change the semantic meaning of the data.

## 2. Preserve Payload Semantics
Preserve all original keys, values, array order, object nesting, text
content, numbers, booleans, and nulls unless a minimal syntax repair is
required to make the JSON valid.

## 3. No Schema Invention
Do not add new fields, remove fields, rename fields, or infer missing
business values. If a value is missing or ambiguous, preserve the closest
original representation rather than inventing content.

## 4. Output JSON Only
Return only the repaired JSON. Do not output explanations, Markdown, code
fences, comments, labels, or commentary.

## 5. Minimal Edit Principle
Make the smallest possible edit that converts the malformed input into
valid JSON.

## 6. Type Preservation
Preserve value types whenever possible. Do not convert strings to numbers,
numbers to strings, booleans to strings, arrays to objects, or objects to
arrays unless the malformed JSON makes the original type unambiguously
recoverable.

## 7. Escaping and Quote Repair
Fix common JSON escaping issues, including unescaped quotes, invalid
backslashes, trailing commas, missing commas, missing closing brackets,
and mismatched braces.

## 8. No Hallucinated Fallback
If the JSON cannot be reliably repaired, return the most structurally
faithful valid JSON representation possible without inventing new semantic
content.

## 9. Contract-Aware Repair
Use the expected output contract only to validate shape and required
top-level structure. Do not use it to invent values that were not present
in the malformed JSON.

# Raw Text
{raw_text}

# Rules
- 剥离聊天话术、前后缀、Markdown fence。
- 只修复 JSON 语法：括号、逗号、引号、转义、截断闭合。
- 不得发明、删除、重解释核心 key/value。
- 若无法可靠修复，输出最小合法 fallback：对象用 `{}`，数组用 `[]`。

# Migration Note
This template has been enriched with the syntax-only JSON repair framework
inherited from the legacy JSON_FIX_PROMPT.
- The current output contract, placeholders, and contract type remain unchanged.
- No new placeholders are introduced.
- No new patch operations, required fields, or brand-new patch intents are introduced.
- Output remains valid JSON only — never Markdown, never explanations, never commentary.
- JSON fix remains a pure syntax repair layer only — not a business logic layer,
  not a content generator, not a patch template.

# Output Contract
仅输出合法 JSON；第一字符必须是 `{` 或 `[`；不得包含解释。

# Examples
Input: ```json\n{"patches": []}\n```
Output: {"patches": []}
Boundary Output: []
Error Fallback: {}
"""

PATCH_GENERATION_TEMPLATE = """# Role
你是顶级 Prompt 优化专家。你要根据当前轮次样本状态、评估结果和错误模式统计，生成结构化 patch 列表。

# Inputs
## Prompt Structure
{prompt_structure}

## Current Prompt
{current_prompt}

## Round Context
{round_context}

## Evaluation Summary
{evaluation_summary}

# Strategy System
## Core Principles
- Be Specific：针对具体错误模式写规则，避免"更仔细"等空泛话术。
- Match Specificity to Failure Frequency：偶发错误追加轻量规则；高频错误使用 checklist / DO NOT 规则。
- Preserve What Works：成功样本依赖的 section 不得改坏；没有错误时输出空数组。
- Improve Conciseness：优先合并冗余规则，不做大段重写。

## Legacy PATCH_GENERATION_PROMPT Four-Strategy Framework
Use the following strategy framework inherited from PATCH_GENERATION_PROMPT.
For each observed failure, pick the most specific applicable strategy and
formulate one patch per strategy — avoid restating the same fix multiple times.

Strategy 1 — Add missing constraint: Use when the failure is caused by an
absent rule, missing condition, missing exception, or missing output
requirement. Formulate a concise addition to the most relevant section.

Strategy 2 — Refine ambiguous instruction: Use when the current prompt
contains a relevant rule but it is vague, overly broad, conflicting with
other sections, or easy to misinterpret. Prefer tightening existing wording
over adding new rules.

Strategy 3 — Add localized example or counterexample: Use when the rule
exists but the model needs a concrete example, boundary case, or
contrastive example to apply it correctly. Keep examples tight and
illustrative — do not invent evidence outside the provided failure context.

Strategy 4 — Tighten output format / decision contract: Use when the failure
is caused by invalid JSON, wrong label vocabulary, a missing required field,
malformed structure, or inconsistent final answer format. Ensure every
patch here only affects the output formatting language, not the upstream logic.

## Patch Scope and Localization
- Generate the smallest patch that fixes the observed failure.
- Prefer editing the most relevant section rather than rewriting broad
  unrelated sections.
- Each patch should address one concrete failure; do not bundle multiple
  independent fixes into a single patch.
- For reasoning, cite the section name or label so downstream audit can
  trace the patch back to its target.

# Operation Priority
Use only operations supported by the current patch schema. Prefer the least
invasive supported operation. Do not invent operation names.

1. `append_to_section`：最安全，新增规则首选。
2. `insert_after` / `insert_before`：需要靠近上下文时使用。
3. `replace_section`：仅当整段结构已失效且能保留全部核心逻辑时使用。
4. `add_after_section`：新增独立主题 section 时使用。
5. `replace_in_section`：高风险，`old_text` 必须 100% 精确匹配。
6. `delete_section`：最危险，除非 section 明确有害且有测试证据，否则避免。

# Safety Rules
- 不得修改 frozen/schema section。
- 不得添加原 prompt 中没有依据的新业务规则。
- 不得绕过 Output Format、安全约束或自检流程。
- 唯一 patch 保护：若 patch 是唯一针对某错误模式且无冲突，必须保留。
- Do not propose edits to protected or frozen sections unless the current
  patch schema explicitly supports such edits. If the relevant text is
  protected, explain the limitation in the patch reasoning if such a field
  exists; otherwise return no patch for that case.
- Only generate patches grounded in the provided failure reason, result
  content, ground truth, and current prompt structure. Do not infer missing
  requirements from outside the provided context.
- If the evaluation result indicates the current prompt already handles this
  case correctly, return an empty patch list. Do not invent improvements
  for passing cases.
- Use `cited_sections` to record the section names your patch targets.
  This field is already supported in the current output schema.

# Migration Note
This template has been enriched with the four-strategy framework and
additional safety guidelines inherited from the legacy PATCH_GENERATION_PROMPT.
- The current patch JSON schema, placeholders, and operation list remain unchanged.
- No new patch operations or new required fields were introduced.
- The four strategy headings and patch localization rules are adapted from
  PATCH_GENERATION_PROMPT; the rest of the template is from the previous
  version.

# Output Contract
返回 JSON 对象：
- `patches`：数组；全部正确时必须为 `[]`。
- `cited_sections`：数组，列出参考 section。
- 每个 patch 需包含 `op`, `target_section` 或 `section_id`, payload 字段, `reasoning`, `risk_level`。
"""

PATCH_SEMANTIC_MERGE_TEMPLATE = """# Role
你是高级 Prompt 策略合并专家，负责将多条 patch 合并为精简、无冲突、可验证的 patch 列表。

# Prompt Structure
{prompt_structure}

# Patches
{patches_json}

# Three-Dimensional Merge Framework
Use the following three-dimension framework to decide which patches to keep,
merge, or drop. Operate dimension-by-dimension; do not skip to final
reduction without first grouping and deduping.

Dimension 1 — Structure Isolation: Group candidate patches by target section
or equivalent section identifier. Only compare or merge patches that affect
the same logical area. Do not merge patches across unrelated sections. Within
each group, deduplicate and resolve conflicts first. Across groups, preserve
independent patches unless there is a clear cross-section conflict.

Dimension 2 — Logic Deduplication: When multiple patches within the same
group express the same intent, keep the clearest and most specific version,
or merge wording into one patch if the current schema supports it. Recurring
patch intent across multiple candidates is a soft priority signal, not a
hard deletion rule — use it to prefer among equivalent fixes, but do not
discard unique valid patches solely because they are rare.

Dimension 3 — Technical Constraints: Preserve JSON schema, supported
operations, patch count validity, locator applicability, and line-level
non-overlap. Use only operations supported by the current patch schema.
Do not invent new operation names, new fields, or new patch object shapes
during merge.

# Group-by-Section Discipline
- First group candidate patches by target section or equivalent section
  identifier.
- Within each group, deduplicate and resolve conflicts.
- Across groups, preserve independent patches unless there is a clear
  cross-section conflict.

# Unique Valid Patch Preservation
If a patch is the only valid patch addressing a distinct failure pattern and
it does not conflict with other patches, preserve it even if no other patch
suggests the same change. Avoid popularity bias: do not drop a valid unique
patch only because a different pattern appears more often in the candidate
list.

# Conflict Resolution
- When two patches conflict, prefer the one with clearer evidence, narrower
  scope, better alignment with the failure reason, and fewer side effects.
- Line-level / locator non-overlap: do not emit merged patches that require
  overlapping edits to the same exact text span unless they have been
  consolidated into one valid patch.

# Operation Priority
append_to_section > insert_after/insert_before > replace_section > add_after_section > replace_in_section > delete_section。

# Migration Note
This template has been enriched with the three-dimension merge framework and
additional safeguards inherited from the legacy PATCH_MERGE_PROMPT.
- The current patch JSON schema, placeholders, and operation list remain unchanged.
- No new patch operations or required fields were introduced.
- Popularity bias is treated as a soft signal only, not a hard deletion rule.
- No fixed compression ratio is enforced; prefer compact results but do not
  force a target ratio.
- The three-dimension framework and group-by-section discipline are adapted
  from PATCH_MERGE_PROMPT; the rest of the template follows the previous
  version's style.

# Merge Strategy
- Be Specific：保留可执行触发条件，不把具体规则泛化成空话。
- Match Specificity：多次出现的同类错误可抽象成通用规则；孤例保持边界限定。
- Preserve What Works：不得删除已证明有效且无冲突的唯一 patch。
- Improve Conciseness：同 section 同意图可合并；不同意图不得硬合并。
- Prefer a compact merged patch list, but do not force a fixed compression
  ratio. Preserve all non-redundant, non-conflicting, valid patches.

# Conflict Checks
- 检查 patch 是否与 Output Format 冲突。
- 检查 patch 是否触碰 frozen schema。
- 检查 patch 是否绕过安全约束、self-check 或不确定性策略。
- 保留唯一非冲突边界 patch；除非有更强理由，不删除孤立 patch。
- Do not merge unrelated section-local patches into a broad global rewrite.
  Merging must preserve original intent and target locality.

# Output Contract
仅输出 JSON 数组。每个元素必须是 patch 对象；失败时返回原 patch 数组作为 fallback。
"""

PATCH_ROOT_AUDIT_TEMPLATE = """# Role
你是 Prompt 跨区域逻辑审查专家，负责终审 patch 列表的全局一致性。

# Prompt Structure
{prompt_structure}

# Patches
{patches_json}

# Cross-Section Audit Framework
Use the following four-dimension audit framework, inherited from the legacy
PATCH_ROOT_MERGE_PROMPT. The goal is to detect cross-section conflicts before
patches are applied, not to introduce new patch content.

Audit Dimension 1 — Rules ↔ Output Format consistency:
Check whether proposed patches change rules, labels, fields, JSON structure,
or decision vocabulary in a way that conflicts with the Output Format section.
Common conflicts include: a rule says output one label but Output Format
defines another label set; a patch adds a JSON field but Output Format does
not define it; a patch adds an exception but no decision rule references it.

Audit Dimension 2 — Workflow ↔ Rules consistency:
Check whether proposed patches add or change workflow steps without
corresponding rule support, or add rules that the workflow never applies.
Common conflicts include: workflow adds a step whose result is never used;
rule section adds a constraint but no workflow step enforces it.

Audit Dimension 3 — Redundancy and duplication:
Detect duplicate or near-duplicate patches across sections. Prefer
consolidation or wording refinement over deleting the only valid patch for
a failure mode. If a patch is the only non-conflicting patch addressing a
distinct failure mode, preserve it. Do not remove unique valid patches merely
because they are low-frequency or not duplicated elsewhere.

Audit Dimension 4 — Orphan protection:
Detect patches that introduce concepts, labels, fields, examples, or
constraints that are not referenced by any related workflow/rule/output
section. When detected, prefer marking as conflicting or adjusting wording
to connect the orphan to an existing section; do not delete a valid patch
solely because its target concept appears orphan.

# Modify-First, Never-Delete-by-Default
When a conflict is found, prefer a minimal modification that preserves the
useful part of the patch. Do not delete a patch unless it is truly redundant,
unsupported, or impossible to reconcile with the prompt contract.

# Audit Discipline
- Do not create brand-new patches during root audit. Only keep, remove, or
  minimally adjust patches already present in the input, if the current
  output contract supports adjustment. Return only audited versions of
  input patches. Do not invent new patch intents.
- Use only the current patch schema and supported operations. Do not invent
  new operation names, fields, decision objects, or patch shapes during
  root audit.
- Do not convert several localized patches into a broad global rewrite.
  Root audit should reduce conflicts while preserving section locality and
  original patch intent.
- Output Format changes are high-impact. Any patch that modifies output
  structure, label vocabulary, required fields, or JSON shape must be
  checked against all related rules and workflow steps.
- Only audit against the provided prompt structure, current prompt, and
  input patches. Do not introduce requirements from outside the provided
  context.

# Migration Note
This template has been enriched with the four-dimension cross-section audit
framework inherited from the legacy PATCH_ROOT_MERGE_PROMPT.
- The current patch JSON schema, placeholders, and operation list remain
  unchanged.
- No new patch operations, required fields, or brand-new patch intents
  are introduced.
- Root audit remains an audit layer, not a patch-generation layer: only
  existing input patches may be kept, adjusted, or removed.
- The four-dimension audit framework and modify-first discipline are
  adapted from PATCH_ROOT_MERGE_PROMPT; the rest of the template follows
  the previous version's style.

# Audit Checks
- Rules/Constraints 不得与 Output Format 或 frozen schema 冲突。
- Workflow patch 不得绕过安全约束、自检或不确定性处理。
- 跨 section 重复意图只保留最合适位置；唯一边界 patch 必须保留。
- 若发现冲突，优先微调使其闭环，禁止无理由删除。
- 严禁新增与输入 patch 无关的新意图。

# Output Contract
仅输出 JSON 数组。成功输出 audited patches；边界情况输出原 patch；错误情况输出 `[]` 并在外部 parser 触发 fallback。
"""

SECTION_REWRITE_TEMPLATE = """# Role
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
"""

LLM_PRUNE_TEMPLATE = """# Role
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
"""

LLM_PRUNE_VALIDATION_TEMPLATE = """# Role
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
成功示例：{"valid": true, "reason": "核心约束和阈值均保留，仅删除重复解释。"}
边界示例：{"valid": false, "reason": "删除了低清晰度时使用 UNCERTAIN 的约束。"}
错误 fallback：{"valid": false, "reason": "validation output invalid"}
"""

PROMPT_NUMBERING_REFACTOR_TEMPLATE = """# Role
你只修复结构化 prompt 的编号。

# Current Prompt
{current_prompt}

# Rules
- 只修改数字/list 编号符号。
- 不得修改措辞、标点、标题层级、顺序或嵌套。
- 不得合并、删除或新增业务规则。
- 仅输出修复后的 prompt body。
"""

PROMPT_FORMAT_REPAIR_TEMPLATE = """# Role
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
"""

PROMPT_STANDARDIZATION_TEMPLATE = """# Role
你将 raw prompt 映射到标准 section 结构，且不改变业务逻辑。

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
- 原始要求语义必须完整保留。
- 不得发明缺失角色、示例或补充指导。
- 中英文术语保持一致；如原文中文为主，输出中文为主。
- 未出现的 section 可省略或按调用方配置留空。
- 仅输出标准化 Markdown。
"""

PROMPT_SELF_CHECK_TEMPLATE = """# Role
你是 Prompt 质量自检审计专家。

# Prompt Text
{prompt_text}

# Declared Schema
{schema_json}

# Checks
- 检查是否存在未声明或拼写错误的占位符。
- 检查约束之间是否矛盾，尤其是 Rules vs Output Format。
- 检查输出格式是否与 schema 字段、类型和 required 一致。
- 检查是否修改或绕过 frozen schema。
- 检查中英文术语、状态值和错误分类是否一致。

# Output Contract
仅输出 JSON：`{"valid": boolean, "issues": [{"severity": "error|warning", "code": string, "message": string}], "recommendation": string}`。
无问题时 issues 为空数组。
"""

DEFAULT_EXAMPLES = {
    "json_fix": [
        {"input": {"raw_text": "```json\n{\"patches\": []}\n```"}, "output": {"patches": []}},
        {"input": {"raw_text": "无法修复的片段"}, "output": {}},
    ],
    "patch_semantic_merge": [
        {"input": {"patches_json": "[{...same intent...}]"}, "output": [{"op": "append_to_section", "reasoning": "合并同类规则"}]},
        {"input": {"patches_json": "[{...unique boundary...}]"}, "output": [{"op": "append_to_section", "reasoning": "唯一边界 patch，保留"}]},
    ],
    "patch_root_audit": [
        {"input": {"patches_json": "[{...no conflict...}]"}, "output": [{"op": "append_to_section", "reasoning": "无跨 section 冲突"}]},
        {"input": {"patches_json": "[{...schema conflict...}]"}, "output": []},
    ],
    "llm_prune_validation": [
        {"input": {"section_content": "原始文本...", "pruned_content": "压缩后文本..."}, "output": {"valid": True, "reason": "核心约束和阈值均保留，仅删除了重复解释"}},
        {"input": {"section_content": "包含 UNCERTAIN 规则", "pruned_content": "删除该规则"}, "output": {"valid": False, "reason": "遗漏不确定性边界"}},
    ],
}


def _contract(kind: str, **extra):
    contract = {
        "type": kind,
        "required": extra.pop("required", []),
        "fields": extra.pop("fields", {}),
        "fallback": extra.pop("fallback", None),
    }
    contract.update(extra)
    return contract


DEFAULT_OPTIMIZER_TEMPLATES = [
    PromptTemplateSpec("patch_text_match", "1.1", "Map fuzzy locator text to a verbatim in-section substring.", ["section_content", "intent_text", "field_type"], _contract("text_or_empty", fields={"text": "verbatim substring"}, fallback=""), PATCH_TEXT_MATCH_TEMPLATE, "low", ["patch", "alignment"]),
    PromptTemplateSpec("patch_translation", "1.1", "Calibrate legacy/free-form patch locator fields while preserving payload.", ["prompt_structure", "current_prompt", "patches_json"], _contract("json_array", fields={"extra.unresolved_locators": "optional string[]"}, fallback="original patch array"), PATCH_TRANSLATION_TEMPLATE, "medium", ["patch", "alignment"]),
    PromptTemplateSpec("patch_translation_retry", "1.1", "Retry one failed patch locator calibration using apply failure details.", ["failure_info", "prompt_structure", "current_prompt", "patch_json"], _contract("json_array", required=["exactly_one_patch"], fields={"extra.unresolved_locators": "optional string[]"}, fallback="original one-patch array"), PATCH_TRANSLATION_RETRY_TEMPLATE, "medium", ["patch", "alignment"]),
    PromptTemplateSpec("json_fix", "1.1", "Repair polluted or malformed JSON after deterministic repair fails.", ["raw_text"], _contract("json", fallback="{} or []"), JSON_FIX_TEMPLATE, "medium", ["analysis", "repair"], DEFAULT_EXAMPLES["json_fix"]),
    PromptTemplateSpec("patch_generation", "1.0", "Generate specific and safe prompt patch candidates from round context.", ["prompt_structure", "current_prompt", "round_context", "evaluation_summary"], _contract("json_object", required=["patches", "cited_sections"], fields={"patches": "Patch[]", "cited_sections": "string[]"}, fallback='{"patches": [], "cited_sections": []}'), PATCH_GENERATION_TEMPLATE, "high", ["patch", "generation"]),
    PromptTemplateSpec("patch_semantic_merge", "1.1", "Generalize and merge related patch candidates before strict validation.", ["prompt_structure", "patches_json"], _contract("json_array", fallback="original patch array"), PATCH_SEMANTIC_MERGE_TEMPLATE, "high", ["patch", "merge"], DEFAULT_EXAMPLES["patch_semantic_merge"]),
    PromptTemplateSpec("patch_root_audit", "1.1", "Audit final patch candidates for cross-section conflicts.", ["prompt_structure", "patches_json"], _contract("json_array", fallback="original patch array or []"), PATCH_ROOT_AUDIT_TEMPLATE, "high", ["patch", "merge"], DEFAULT_EXAMPLES["patch_root_audit"]),
    PromptTemplateSpec("section_rewrite", "1.1", "Rewrite a single section while preserving existing rule intent.", ["section_header", "section_content", "optimization_instruction"], _contract("text", fallback="original section"), SECTION_REWRITE_TEMPLATE, "high", ["patch", "rewrite"]),
    PromptTemplateSpec("llm_prune", "1.1", "Prune one section without adding or losing rules.", ["section_header", "section_content"], _contract("text", fallback="original section"), LLM_PRUNE_TEMPLATE, "high", ["compression"]),
    PromptTemplateSpec("llm_prune_validation", "1.1", "Validate semantic equivalence after LLM pruning.", ["original_section", "pruned_section"], _contract("json_object", required=["valid", "reason"], fields={"valid": "boolean", "reason": "string"}, fallback='{"valid": false, "reason": "invalid"}'), LLM_PRUNE_VALIDATION_TEMPLATE, "medium", ["compression", "validation"], DEFAULT_EXAMPLES["llm_prune_validation"]),
    PromptTemplateSpec("prompt_numbering_refactor", "1.1", "Fix numbering only, preserving prompt text and structure.", ["current_prompt"], _contract("text", fallback="original prompt"), PROMPT_NUMBERING_REFACTOR_TEMPLATE, "low", ["prompt", "format"]),
    PromptTemplateSpec("prompt_format_repair", "1.1", "Normalize prompt formatting without semantic changes.", ["issues_description", "original_prompt"], _contract("text", fallback="original prompt"), PROMPT_FORMAT_REPAIR_TEMPLATE, "medium", ["prompt", "format"]),
    PromptTemplateSpec("prompt_standardization", "1.1", "Map raw prompt content into a standard section structure losslessly.", ["original_prompt"], _contract("text", fallback="original prompt"), PROMPT_STANDARDIZATION_TEMPLATE, "medium", ["prompt", "format"]),
    PromptTemplateSpec("prompt_self_check", "1.0", "Audit prompt quality against placeholders, contradictions, and schema alignment.", ["prompt_text", "schema_json"], _contract("json_object", required=["valid", "issues", "recommendation"], fields={"valid": "boolean", "issues": "Issue[]", "recommendation": "string"}, fallback='{"valid": false, "issues": [], "recommendation": "manual review"}'), PROMPT_SELF_CHECK_TEMPLATE, "medium", ["prompt", "validation"]),
]


def build_default_template_registry() -> PromptTemplateRegistry:
    registry = PromptTemplateRegistry()
    for template in DEFAULT_OPTIMIZER_TEMPLATES:
        registry.register(template)
    return registry
