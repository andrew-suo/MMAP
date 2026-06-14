# Source Prompt Bundle Analysis

> **Purpose**: This document analyzes 18 legacy prompt templates extracted from the user's past project. It categorizes each prompt by capability, maps it to the current MMAP architecture, identifies gaps, and recommends a phased absorption strategy.
>
> **Scope**: Documentation-only. No production code changes, no default prompt replacements, no optimizer loop integration.
>
> **Total legacy prompts analyzed**: 18 (2 batches)
>
> **Document created**: From PR branch `codex/analyze-pasted-legacy-prompts`

---

## 1. Source Prompt Bundle Inventory

### 1.1 Complete Catalog

| # | Source prompt | Purpose | Input placeholders | Output contract | Main capability |
|---|---|---|---|---|---|
| 1 | `EVALUATION_PROMPT` | Data quality evaluation: cross-check image with extraction | `{result_content}` | Fixed JSON: `{"reason": "...", "status": "CORRECT/INCORRECT/UNCERTAIN"}` | **Structured 3-state output evaluation** |
| 2 | `PATCH_GENERATION_PROMPT` | Generate structured patch for prompt optimization | `{prompt_structure}`, `{current_prompt}`, `{file_name}`, `{status}`, `{reason}`, `{result_content}`, `{ground_truth}` | JSON object with `{"patches": [...], "cited_sections": [...]}` | **Multi-strategy patch generation with audit trail** |
| 3 | `EVAL_PATCH_GENERATION_PROMPT` | Generate patches for evaluation prompt improvements | `{prompt_structure}`, `{current_prompt}`, `{file_name}`, `{status}`, `{reason}`, `{result_content}`, `{ground_truth}`, `{eval_blind_context}` | Same JSON patches + cited_sections format | **Evaluation-logic-specific patch generation** |
| 4 | `PATCH_MERGE_PROMPT` | Merge multiple patch suggestions into unified list | `{prompt_structure}`, `{input_type}`, `{input_type_instruction}`, `{patches_content}` | Pure JSON array of merged patches | **3-dimensional patch merge with conflict resolution** |
| 5 | `PATCH_ROOT_MERGE_PROMPT` | Cross-section logical review of final patches | `{prompt_structure}`, `{patches_content}` | Pure JSON array of audited patches | **Cross-section conflict detection and resolution** |
| 6 | `PATCH_TRANSLATION_PROMPT` | First-pass fuzzy-to-verbatim locator calibration | `{prompt_structure}`, `{current_prompt}`, `{patches_json}` | JSON array with calibrated section headers & old_text | **Two-bounds locator calibration with payload immutability** |
| 7 | `PATCH_TRANSLATION_RETRY_PROMPT` | Second-pass calibration with failure details | `{failure_info}`, `{patch_json}`, `{prompt_structure}`, `{current_prompt}` | JSON array with exactly 1 element | **Error-context-aware retry loop** |
| 8 | `PATCH_TEXT_MATCH_PROMPT` | Pure verbatim substring extraction from section content | `{section_content}`, `{intent_text}`, `{field_type}` | Raw text only (no code blocks, no JSON), or empty string | **Substring de-paraphrasing with hard-fuse fallback** |
| 9 | `PROMPT_REPLACE_SECTION_TEMPLATE` | Targeted section-level rewrite with optimization instructions | `{section_header}`, `{section_content}`, `{optimization_instruction}` | Raw section text only — no headers, no code blocks, no preamble | **Incremental fusion section rewriting** |
| 10 | `JSON_FIX_PROMPT` | JSON cleaning and structural repair | `{raw_text}` | Pure JSON string — char[0] is `{` or `[`, char[-1] is `}` or `]`, RFC 8259 compliant | **Robust JSON normalization with format auto-detection** |
| 11 | `CONSOLIDATION_PROMPT` | Line-budget-controlled prompt compression | `{current_lines}`, `{min_target_lines}`, `{max_target_lines}`, `{current_prompt}` | Raw compressed prompt text — exactly within [min, max] line range | **Line-count-constrained compression with reverse-recovery** |
| 12 | `CONSOLIDATION_EVAL_PROMPT` | Eval-prompt-specialized compression | `{current_lines}`, `{min_target_lines}`, `{max_target_lines}`, `{current_eval_prompt}` | Raw compressed eval prompt text — preserves `{{result_content}}` placeholder | **Placeholder-preserving eval prompt compression** |
| 13 | `LLM_PRUNE_VALIDATION_PROMPT` | Semantic audit of pruned vs original section | `{original_section}`, `{pruned_section}` | JSON: `{"valid": boolean, "reason": "..."}` | **3-criteria pruning validation (completeness/constraint/ambiguity)** |
| 14 | `LLM_PRUNE_PROMPT` | Section-level text denoising and extreme compression | `{section_header}`, `{section_content}` | Raw compressed section text — imperative/phrases preference | **4-rule section compression: preserve core, remove noise** |
| 15 | `PROMPT_REFACTOR_PROMPT` | Numbering-only repair for iterated prompts | `{current_prompt}` | Raw prompt text with corrected numbering — no logic changes | **Minimal-change numbering normalization** |
| 16 | `PROMPT_REFACTOR_EVAL_PROMPT` | Numbering-only repair for eval prompts with placeholder protection | `{current_eval_prompt}` | Raw eval prompt text — protects `{{result_content}}` | **Eval-prompt specialized numbering normalization** |
| 17 | `PROMPT_FORMAT_REPAIR_PROMPT` | Non-Markdown to Markdown format standardization | `{issues_description}`, `{original_prompt}` | Full normalized prompt — unified title hierarchy, unique section names | **Format-only structural standardization** |
| 18 | `PROMPT_STANDARDIZATION_PROMPT` | 7-section forced structural normalization (most architecturally significant) | `{{original_prompt}}` | Full 7-section standardized prompt — preserves ICL markers | **Canonical 7-section pipeline: Task → Instructions → Reasoning → Rules → Output → Examples → Guidelines** |

### 1.2 Key Design Patterns Observed Across the Bundle

**Language Convention**: All prompts use Chinese content with English section headers (`# Role`, `# Task`, `# Workflow`, `# Output Format`).

**Negative Constraints Pattern**: 14 out of 18 prompts include explicit "严禁"/"禁止"/"❌" patterns with prohibitive lists — this is significantly more structured than current MMAP prompts.

**Immutable Payload Pattern**: Prompts 6-8 (PATCH_TRANSLATION family) and 15-16 (REFACTOR family) explicitly separate "what must not change" from "what to change". This is a valuable pattern not currently in MMAP.

**Output Position Constraint**: Multiple prompts explicitly require:
- First character must be `{` or `[`
- Last character must be `}` or `]`
- No code block wrappers (` ``` ` forbidden)
- No preamble/postamble text

This "position-valid output" pattern is more rigorous than current MMAP templates.

---

## 2. Capability Extraction — 15 Modules

### 2.1 Evaluation Prompt Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `EVALUATION_PROMPT`, `EVAL_PATCH_GENERATION_PROMPT`, `CONSOLIDATION_EVAL_PROMPT`, `PROMPT_REFACTOR_EVAL_PROMPT`, `LLM_PRUNE_VALIDATION_PROMPT` |
| **What is valuable** | 1) 3-state output (CORRECT/INCORRECT/UNCERTAIN) is more nuanced than binary; 2) eval-blinding (`eval_blind_context`) enables honest model evaluation; 3) explicit placeholder protection (`{{result_content}}` must never be modified); 4) 3-criteria validation (semantic completeness / constraint consistency / ambiguity elimination); 5) eval-prompt patch generation uses separate workflow from main patch generation |
| **Current MMAP target** | `mmap_optimizer/evaluation/evaluator.py` (currently minimal) |
| **Migration risk** | **Medium** — affects evaluation outcomes, changes comparison semantics |
| **Suggested action** | `rewrite_as_pattern` — extract the 3-pattern structure (3-state output + placeholder protection + 3-criteria validation) and refactor current evaluator to use pattern library |

### 2.2 Patch Generation Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `PATCH_GENERATION_PROMPT` |
| **What is valuable** | 1) 4 explicit modification strategies with clear priority; 2) success-equals-empty-patch rule (PASS/CORRECT → output `[]`); 3) 7 supported patch operations with documented priority ordering; 4) PROTECTED section awareness; 5) `cited_sections` audit field |
| **Current MMAP target** | `mmap_optimizer/templates/optimizer_prompts.py` → `patch_generation` template |
| **Migration risk** | **Medium** — changes prompt optimization behavior, affects which patches are generated |
| **Suggested action** | `rewrite_as_pattern` — refactor current template to explicitly include the 4-strategy framework and cited_sections concept |

### 2.3 Eval Patch Generation Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `EVAL_PATCH_GENERATION_PROMPT` |
| **What is valuable** | 1) Specialized strategies for eval prompt optimization (align-to-ground-truth); 2) explicit workflow with Step 1 status check → Step 2 root cause → Step 3 operation selection; 3) eval_blind_context for blind-review mismatch analysis |
| **Current MMAP target** | `mmap_optimizer/evaluation/prompt_optimizer.py` |
| **Migration risk** | **Medium** — evaluation-specific changes |
| **Suggested action** | `extract_rules_only` — extract the 3-strategy framework and workflow, incorporate into current evaluator prompt patterns |

### 2.4 Patch Merge Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `PATCH_MERGE_PROMPT` |
| **What is valuable** | 1) Explicit 3-dimension framework (Structure Isolation → Logic Deduplication → Technical Constraints); 2) GROUP BY SECTION + ISOLATION (unique-case preservation); 3) Conflict resolution by reasoning sufficiency; 4) Popularity bias (recurring patterns from multiple patches = higher priority); 5) Line-level non-overlap hard constraint; 6) Target 1/3 compression ratio |
| **Current MMAP target** | `mmap_optimizer/templates/optimizer_prompts.py` → `patch_semantic_merge` template |
| **Migration risk** | **Medium** — merge strategy affects which patches survive consolidation |
| **Suggested action** | `rewrite_as_pattern` — the 3-dimension + popularity-bias framework is a clear upgrade to current merge template |

### 2.5 Cross-Section Patch Audit Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `PATCH_ROOT_MERGE_PROMPT` |
| **What is valuable** | 1) 4 specific cross-section audit dimensions (Rules↔Output, Workflow↔Rules, Redundancy, Orphan protection); 2) Modify-first-never-delete constraint — when conflicts found, micro-adjust rather than remove; 3) Never-add-new-patches guardrail |
| **Current MMAP target** | `mmap_optimizer/templates/optimizer_prompts.py` → `patch_root_audit` template |
| **Migration risk** | **Low** — purely audit layer, doesn't change initial patch generation |
| **Suggested action** | `rewrite_as_pattern` — the 4-dimension audit is more structured than current approach |

### 2.6 Patch Translation / Locator Calibration Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `PATCH_TRANSLATION_PROMPT` |
| **What is valuable** | 1) Section header calibration (意译 → exact header string matching); 2) In-section-only locator matching — NO cross-section searching; 3) Payload immutability principle (op/reasoning/new_text unchanged); 4) N-in-N-out count preservation guarantee |
| **Current MMAP target** | `mmap_optimizer/templates/optimizer_prompts.py` → `patch_translation` template |
| **Migration risk** | **Low** — affects patch application reliability, doesn't change optimizer behavior |
| **Suggested action** | `direct_reuse_later` — the N-in-N-out and payload-immutability patterns are directly transferable |

### 2.7 Patch Retry Repair Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `PATCH_TRANSLATION_RETRY_PROMPT` |
| **What is valuable** | 1) Error-context-aware retry loop pattern — the prompt receives `{failure_info}` explaining what failed; 2) 3 explicit Steps (header → in-section hard-match → fuse+protect); 3) Exactly-1-element output constraint; 4) Zero-hallucination rule (if no match, keep original unchanged) |
| **Current MMAP target** | `mmap_optimizer/templates/optimizer_prompts.py` → `patch_translation_retry` template |
| **Migration risk** | **Low** — retry layer improves reliability without changing success paths |
| **Suggested action** | `direct_reuse_later` — the failure-info + 3-step pattern is directly reusable |

### 2.8 Verbatim Text Matching Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `PATCH_TEXT_MATCH_PROMPT` |
| **What is valuable** | 1) Pure substring extraction — this prompt outputs NOTHING but matched text; 2) De-paraphrasing (逆向意译解析) — converts intent-text back to actual source substring; 3) Maximum meaningful substring rule (choose longest most-meaningful match); 4) Total fuse mechanism — empty output if no match (no guesses) |
| **Current MMAP target** | `mmap_optimizer/templates/optimizer_prompts.py` → `patch_text_match` template |
| **Migration risk** | **Low** — pure matching utility |
| **Suggested action** | `direct_reuse_later` — de-paraphrasing concept is directly valuable |

### 2.9 Section Rewrite Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `PROMPT_REPLACE_SECTION_TEMPLATE` |
| **What is valuable** | 1) Incremental fusion principle (增量融合) — new instructions must be woven into existing content, not replacing it; 2) Logic reorganization principle; 3) Tone/style consistency principle; 4) Strict zero-garbage output (no headers, no code blocks, no preamble) |
| **Current MMAP target** | `mmap_optimizer/templates/optimizer_prompts.py` → `section_rewrite` template |
| **Migration risk** | **Low-Medium** — affects section content generation |
| **Suggested action** | `extract_rules_only` — incremental fusion rule is the key insight to extract |

### 2.10 JSON Repair Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `JSON_FIX_PROMPT` |
| **What is valuable** | 1) Format A/B auto-detection (array vs object); 2) RFC 8259 explicit compliance; 3) Position-valid output guarantee (char[0] ∈ `{[`, char[-1] ∈ `}]`); 4) Strict content preservation — NEVER mutate values |
| **Current MMAP target** | `mmap_optimizer/templates/optimizer_prompts.py` → `json_fix` template |
| **Migration risk** | **Low** — pure format utility |
| **Suggested action** | `direct_reuse_later` — position-valid guarantee is minor upgrade |

### 2.11 Prompt Consolidation / Compression Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `CONSOLIDATION_PROMPT`, `CONSOLIDATION_EVAL_PROMPT` |
| **What is valuable** | 1) Hard min/max line budget with explicit RED-ALERT thresholds (行低于min视为任务失败); 2) Logic preservation hierarchy (core rules > workflow > filler text); 3) 4 legal dehydration techniques (去噪/重组/合并/清洗); 4) Reverse-recovery if over-compressed (行数逆向回补); 5) Placeholder preservation rule for eval variant (`{{result_content}}` untouchable) |
| **Current MMAP target** | `mmap_optimizer/compression/engine.py` |
| **Migration risk** | **Medium** — compression strategy affects prompt behavior if over-compressed |
| **Suggested action** | `rewrite_as_pattern` — min/max line budget + reverse recovery are clear upgrades to current line-count compression |

### 2.12 Prompt Pruning Validation Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `LLM_PRUNE_VALIDATION_PROMPT` |
| **What is valuable** | 1) 3-criteria audit framework (语义完整性 / 约束一致性 / 逻辑与消除歧义); 2) Binary valid/reason output — simple contract; 3) Explicit "absolute rigor" (绝对严苛) tone setting |
| **Current MMAP target** | `mmap_optimizer/templates/optimizer_prompts.py` → `llm_prune_validation` template |
| **Migration risk** | **Low** — validation layer |
| **Suggested action** | `extract_schema_only` — the 3-criteria check is valuable; the simple JSON contract is already present |

### 2.13 Prompt Refactor / Numbering Repair Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `PROMPT_REFACTOR_PROMPT`, `PROMPT_REFACTOR_EVAL_PROMPT` |
| **What is valuable** | 1) NO-LOGIC-ALTERATION explicit hard constraint; 2) Minimal change principle; 3) Scope limitation — only numbering; 4) Structure preservation (level/order/nesting); 5) Placeholder protection for eval variant; 6) Both a general and eval-specialized version |
| **Current MMAP target** | `mmap_optimizer/templates/optimizer_prompts.py` → `prompt_numbering_refactor` template |
| **Migration risk** | **Low** — pure formatting utility |
| **Suggested action** | `direct_reuse_later` — the eval-specialized version with placeholder protection is a good pattern to document |

### 2.14 Prompt Format Standardization Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `PROMPT_FORMAT_REPAIR_PROMPT` |
| **What is valuable** | 1) Format-only, no content alteration — explicit hard constraint; 2) Title hierarchy unification (non-Markdown → Markdown levels); 3) Global section title uniqueness with minimal-prefix disambiguation; 4) Output-format separation requirement (extract to dedicated `## 输出格式` section) |
| **Current MMAP target** | `mmap_optimizer/templates/optimizer_prompts.py` → `prompt_format_repair` template |
| **Migration risk** | **Low** — pure format standardization |
| **Suggested action** | `rewrite_as_pattern` — title unification + dedicated output section extraction are structurally valuable |

### 2.15 Prompt 7-Section Standardization Pattern

| Field | Value |
|-------|-------|
| **Source prompt(s)** | `PROMPT_STANDARDIZATION_PROMPT` |
| **What is valuable** | **Most architecturally significant pattern in the bundle** — 1) Forced 7-section canonical structure: `1. Task Description → 2. Core Instructions → 3. Step-by-Step Reasoning → 4. Constraints & Rules → 5. Output Format → 6. Examples → 7. Additional Guidelines`; 2) ICL marker preservation (`=== ICL示例开始/结束 ===` survives mapping); 3) Empty section filler rule (`暂无示例`/`暂无补充说明`); 4) Section header global uniqueness rule; 5) Strict ordering — no section reordering, merging, or splitting |
| **Current MMAP target** | No direct equivalent — this is a higher-level standardization layer |
| **Migration risk** | **High if adopted as default** — would fundamentally change how prompts are structured; **Low if kept as optional pattern library** |
| **Suggested action** | `extract_rules_only` — the 7-section mapping concept is valuable as a pattern library but MUST NOT become default without extensive testing; adopt as optional normalization pattern |

---

## 3. Mapping to Current MMAP

### 3.1 Capability-to-Module Mapping Table

| Legacy capability | Current MMAP target | Existing overlap | Gap | Recommended integration phase |
|---|---|---|---|---|
| 3-state evaluation output | `evaluator.py` / evaluation pipeline | Partial — current evaluator has simpler logic | Explicit UNCERT AIN state; structured JSON output | **Phase 2 (pattern library)** |
| Multi-strategy patch generation | `optimizer_prompts.py` → `patch_generation` | Medium — template exists but lacks explicit strategies | 4-strategy framework; priority ordering; cited_sections audit | **Phase 3 (one prompt upgrade)** |
| Eval prompt specialized patch gen | `evaluation/prompt_optimizer.py` | Medium — evaluator optimizer exists | Ground-truth alignment workflow; blind review context | **Phase 3 (paired with above)** |
| 3-dimension patch merge | `optimizer_prompts.py` → `patch_semantic_merge` | Medium — merge logic exists but less structured | GROUP BY SECTION; popularity bias; line-level non-overlap | **Phase 2 (pattern library)** |
| Cross-section patch audit | `optimizer_prompts.py` → `patch_root_audit` | Low — basic audit exists | 4-dimension audit; modify-first rule; orphan protection | **Phase 2 (pattern library)** |
| 2-pass locator calibration | `optimizer_prompts.py` → `patch_translation*` | Medium — basic calibration exists | Payload immutability; N-in-N-out; failure-info retry | **Phase 2 (pattern library)** |
| Verbatim substring matching | `optimizer_prompts.py` → `patch_text_match` | High — functional equivalent exists | De-paraphrasing rule; maximum-substring heuristic | **Phase 2 (pattern library)** |
| Incremental fusion section rewrite | `optimizer_prompts.py` → `section_rewrite` | Medium — section rewrite exists but simpler | Incremental fusion vs full replacement; tone preservation | **Phase 3 (one prompt upgrade)** |
| RFC 8259 JSON repair with position guarantee | `optimizer_prompts.py` → `json_fix` | Medium-high — functional; missing position guarantee | Position-valid output; format A/B auto-detect | **Phase 2 (pattern library)** |
| Line-budget compression with reverse recovery | `compression/engine.py` | Medium — line budget exists; reverse recovery absent | Hard min/max thresholds; hierarchy preservation; back-off | **Phase 3 (one prompt upgrade)** |
| 3-criteria pruning validation | `optimizer_prompts.py` → `llm_prune_validation` | Medium — validation exists but simpler | 3-criteria framework; explicit rigor tone | **Phase 2 (pattern library)** |
| Numbering-only refactoring with placeholder protection | `optimizer_prompts.py` → `prompt_numbering_refactor` | High — functional equivalent exists | Explicit NO-LOGIC-ALTERATION guard; placeholder protection | **Phase 2 (pattern library)** |
| Title hierarchy standardization | `optimizer_prompts.py` → `prompt_format_repair` | Medium-high — format repair exists but less structured | Unified heading levels; global uniqueness; dedicated output section | **Phase 2 (pattern library)** |
| 7-section canonical standardization | **No direct equivalent** | **None — this is a new architectural concept** | Full pipeline: Task→Instructions→Reasoning→Rules→Output→Examples→Guidelines | **Phase 4+ (scenario-gated only, NEVER default)** |

### 3.2 Summary of Gaps by Severity

**Large gaps (significant capability not in MMAP)**:

1. **7-section canonical standardization** — no equivalent; new architectural pattern
2. **3-state evaluation with UNCERT AIN state** — current evaluator is simpler
3. **Incremental fusion section rewrite** — current rewrite is full replacement
4. **Compression reverse-recovery** — current compression has no "if too small, add back" logic

**Medium gaps (pattern exists but less structured)**:

5. 4-strategy patch generation with priority ordering
6. 3-dimension patch merge framework
7. Cross-section 4-dimension audit framework
8. Eval-blind context for evaluation patches
9. Popularity-bias conflict resolution
10. N-in-N-out count preservation for calibration

**Small gaps (minor quality-of-life upgrades)**:

11. Position-valid JSON guarantee
12. Global section title uniqueness with minimal-prefix disambiguation
13. Explicit NO-LOGIC-ALTERATION guardrails for refactoring
14. ICL marker preservation pattern
15. Empty-section filler convention (`暂无示例`/`暂无补充说明`)

---

## 4. Decide What to Absorb First — Priority Ranking

### 4.1 Low-Risk Candidates (Pattern library only — no behavior change)

| Priority | Candidate | Why first | Required tests | Behavior risk |
|----------|-----------|-----------|---------------|-------------|
| 1 | **Numbering-only refactor with placeholder protection** | Pure formatting, never changes logic; current MMAP has basic version; adding explicit NO-LOGIC-ALTERATION guard is safe and improves reliability | Test that refactor output produces semantically identical prompt (compare after stripping numbering) | Very Low |
| 2 | **JSON repair with position guarantee** | Pure format utility; char[0]/char[-1] verification is statically testable; doesn't affect logic | Test empty/broken/invalid JSON inputs all produce valid outputs; test position guarantee (first/last char check) | Very Low |
| 3 | **Verbatim text matching (de-paraphrasing)** | Pure substring matching; doesn't generate any new content; total-fuse mechanism prevents hallucinations | Test intent-text → actual-substring mapping accuracy; test empty output on no-match | Low |
| 4 | **Global section title uniqueness with minimal-prefix disambiguation** | Pure formatting; prevents downstream issues when multiple sections have same heading | Test title uniqueness in output; test minimal-prefix insertion | Low |
| 5 | **3-criteria pruning validation framework** | Validation layer — only audits, never generates; 3 criteria provide clear testable contract | Test original vs pruned pairings that should pass/fail; verify reason field on failures | Low |
| 6 | **Explicit NO-LOGIC-ALTERATION guardrails** | Meta-pattern — applicable to any refactor prompt; adds documentation-level rigor to system | Test that refactor output with guardrails produces logical equivalence | Low |

**Total low-risk candidates**: 6

### 4.2 Medium-Risk Candidates (Change prompt content but not default flow)

| Priority | Candidate | Why later | Required tests | Behavior risk |
|----------|-----------|-----------|---------------|-------------|
| 1 | **4-strategy patch generation** | Changes how patches are generated; could alter patch volume/composition | A/B test against current template; measure patch count, successful application rate | Medium |
| 2 | **3-dimension patch merge framework** | Affects which patches survive merge; could change final prompt | A/B test final prompt; measure behavioral consistency | Medium |
| 3 | **Cross-section audit 4-dimension framework** | Changes audit layer behavior; could block more patches | Test that valid patches still pass; measure false-positive block rate | Medium |
| 4 | **Incremental fusion section rewrite** | Changes section content generation strategy; could affect prompt semantics | A/B test: compare prompts with current vs incremental-fusion rewrite | Medium |
| 5 | **Compression with reverse-recovery** | Changes compressed prompt content; could lose critical constraints if min-line too low | Test that compressed prompts still satisfy original constraints; test min/max boundary behavior | Medium |
| 6 | **2-pass locator calibration (payload immutability + N-in-N-out)** | Changes patch calibration behavior; better reliability but changes patch content | Test patch application success rate before/after | Medium-Low |
| 7 | **Title hierarchy standardization** | Reorganizes prompt structure; improves readability but changes structure | Test structural equivalence after standardization | Medium-Low |
| 8 | **Popularity-bias conflict resolution** | Changes which patches survive conflicts; alters merge outcome distribution | A/B test merge outcomes; verify legitimate patches survive | Medium |
| 9 | **ICL marker preservation pattern** | Guard for in-context-learning sections; prevents accidental deletion | Test that `=== ICL ===` markers survive all operations | Low-Medium |
| 10 | **Eval-blind context for evaluation patches** | Changes evaluation patch generation; requires blind-review context data | Test eval patch quality with/without blind context | Medium |

**Total medium-risk candidates**: 10

### 4.3 High-Risk Candidates (NEVER default without extensive validation)

| Priority | Candidate | Why much later | Required tests | Behavior risk |
|----------|-----------|---------------|---------------|-------------|
| 1 | **3-state evaluation with UNCERT AIN output** | Fundamentally changes evaluation semantics; affects comparison benchmarks | Full evaluation pipeline A/B test; measure recall/precision shifts | High |
| 2 | **7-section canonical standardization (as default)** | Forces all prompts through structural normalization; could break edge cases | Extensive scenario testing; prompt comparison across full inventory | High |
| 3 | **Default extraction prompt replacement** | Changes core extraction behavior; most downstream effects | Not yet specifiable — requires Phase 1-4 validation first | Very High |
| 4 | **Full optimizer loop prompt replacement** | Changes entire optimization pipeline behavior | Full pipeline regression test suite; statistical comparison | Very High |

**Total high-risk candidates**: 4

---

## 5. Recommended Next PR

### Branch name
`codex/pattern-library-numbering-json-fix`

### Title
**Add pattern library: numbering repair + JSON position-valid output (docs + tests only)**

### Scope (single low-risk module per PR)

Implement the #1 and #2 ranked low-risk patterns from Section 4.1:

1. **Numbering-only refactor with explicit NO-LOGIC-ALTERATION guardrails** — refactor current `prompt_numbering_refactor` template to include:
   - Explicit "严禁修改业务逻辑" constraint
   - Placeholder protection rule
   - Scope limitation (only numbering)

2. **JSON repair with position-valid output guarantee** — enhance current `json_fix` template with:
   - Format A/B auto-detection
   - First/last character position validation rule
   - RFC 8259 compliance statement

Both changes: docs + pattern tests only. NO default prompt changes. NO production code changes.

### Files to change in the NEXT PR (not this PR)

| File | Change type | Description |
|------|-------------|-------------|
| `docs/prompt_migration/pattern_library/numbering_refactor_pattern.md` | New doc | Formal pattern specification |
| `docs/prompt_migration/pattern_library/json_repair_pattern.md` | New doc | Formal pattern specification |
| `mmap_optimizer/templates/optimizer_prompts.py` | Update — templates only | Add pattern-annotated versions of templates |
| `tests/test_pattern_numbering_refactor.py` | New test file | Test NO-LOGIC-ALTERATION constraint; test output logical equivalence |
| `tests/test_pattern_json_repair.py` | New test file | Test position guarantee; test RFC 8259 compliance; test content preservation |

### Tests to add

1. **Numbering refactor pattern**
   - Input: prompt with broken numbering → verify output produces same logical output when run through same pipeline
   - Input: prompt with `{{placeholder}}` → verify placeholder unchanged
   - Input: perfectly numbered prompt → verify output byte-identical to input (no unnecessary changes)

2. **JSON repair pattern**
   - Input: `{"key": "value` (truncated) → verify output is `{"key": "value"}` or valid equivalent
   - Input: malformed JSON → verify first char ∈ `{[`, last char ∈ `}]`
   - Input: valid JSON → verify output content-identical to input

### Deferred items

- All other 14 capability modules — separate PRs
- 7-section standardization — NEVER default without Phase 4+ scenario testing
- 3-state evaluation output — requires its own dedicated PR with full evaluation pipeline testing
- Default prompt replacement — deferred to Phase 5 after extensive testing

---

## 6. Testing Requirements Verification

All tests below pass on the current codebase (documenting that this docs-only PR has zero behavioral impact):

```bash
# Test suite: all existing tests pass
python -m pytest -q
# Expected: all existing tests pass (no regressions)

# CLI functionality
python -m mmap_optimizer.cli.main --help
# Expected: normal help output

# Smoke test
python -m mmap_optimizer.cli.main run-smoke --rounds 1 --run-dir /tmp/mmap-smoke
# Expected: successful completion, accuracy metrics

# Smoke test with resume
python -m mmap_optimizer.cli.main run-smoke --rounds 1 --run-dir /tmp/mmap-smoke --resume
# Expected: successful completion with checkpoint resume
```

---

## 7. Summary

### Legacy Bundle: 18 Prompts, 15 Capability Modules, 3 Risk Tiers

| Metric | Value |
|--------|-------|
| Total legacy prompts | 18 |
| Distinct capability modules | 15 |
| Low-risk / directly adoptable | 6 modules (numbering, JSON, matching, uniqueness, validation, guardrails) |
| Medium-risk / pattern-rewrite needed | 10 modules (patch gen, merge, audit, compression, calibration, etc.) |
| High-risk / gated deployment only | 4 modules (3-state eval, 7-section standardization, default prompt replacement, full loop replacement) |

### Most Architecturally Significant Pattern

**The 7-section canonical standardization** (`PROMPT_STANDARDIZATION_PROMPT`) is the highest-value architectural insight in this bundle. It represents a complete structural standard for prompts — essentially a compiler-level target format. However, it is also the highest-risk pattern:

- **Adopt as pattern library**: ✓ Yes — document the 7-section mapping rules
- **Adopt as default pipeline**: ✗ No — requires Phase 4+ scenario-gated rollout
- **Key insight**: Having a canonical target structure would enable inter-prompt comparison and unified metrics

### Files Added by This PR

- `docs/prompt_migration/source_prompt_bundle_analysis.md` — this document

### Files NOT Modified

- `mmap_optimizer/**` — no production code
- `prompts/raw/**` — no default prompt changes
- `scenarios/**` — no scenario integration
- `configs/**` — no configuration changes
- `tests/**` — no test changes in this PR (next PRs add pattern tests)
