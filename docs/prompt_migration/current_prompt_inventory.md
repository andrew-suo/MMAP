# Current Prompt Inventory

This document catalogs all prompt-related assets in the current MMAP codebase as of PR #45. It serves as the baseline for the prompt migration and absorption plan.

## 1. Raw Prompt Files

### `prompts/raw/extraction.txt`
- **Purpose**: Primary extraction prompt for the task
- **Complexity**: 36 lines, moderate
- **Sections**: Role definition, workflow, criteria, boundary handling, forbidden behaviors, output format
- **Coverage**: Partial test coverage via `test_prompt_evaluator.py`, `test_prompt_quality_and_ab.py`
- **Core**: Yes
- **Enhanceable**: Yes (see weakness analysis)

### `prompts/raw/analysis.txt`
- **Purpose**: Analysis prompt for patch generation and root cause analysis
- **Complexity**: 30 lines, moderate
- **Sections**: Role definition, analysis workflow, fact/hypothesis/patch distinction, patch quality standards, output schema
- **Coverage**: Partial test coverage via `test_llm_repair_semantic_and_prompt_tools.py`
- **Core**: Yes
- **Enhanceable**: Yes (see weakness analysis)

### `scenarios/default/prompts/system.md`
- **Purpose**: Simple system prompt for scenario mode
- **Complexity**: 1 line, minimal
- **Coverage**: No dedicated tests
- **Core**: No (scenario-specific)
- **Enhanceable**: Low priority

## 2. Prompt Infrastructure Modules

### `mmap_optimizer/prompt/ir.py`
- **Classes**: `PromptSection`, `PromptIR`
- **Purpose**: Core data structures for structured prompt representation
- **Key Fields**: `id`, `type`, `content`, `mutability`, `compressibility`, `rendering_order`
- **Coverage**: Tested indirectly via `test_prompt_evaluator.py`
- **Core**: Yes
- **Enhanceable**: Low (infrastructure is solid)

### `mmap_optimizer/prompt/initializer.py`
- **Functions**: `initialize_prompt_version`, `initialize_prompt_from_file`
- **Purpose**: Parses raw prompt text into structured PromptIR with predefined section mapping
- **Section Mapping**: `EXTRACTION_SECTIONS` (12 sections), `ANALYSIS_SECTIONS` (13 sections)
- **Coverage**: Tested via `test_prompt_evaluator.py`
- **Core**: Yes
- **Enhanceable**: The section mapping is hardcoded; could be made configurable

### `mmap_optimizer/prompt/renderer.py`
- **Classes**: `RenderedPrompt`, `PromptRenderer`
- **Purpose**: Converts PromptIR to rendered text with optional section markers
- **Coverage**: Tested indirectly
- **Core**: Yes
- **Enhanceable**: Low

### `mmap_optimizer/prompt/contract.py`
- **Classes**: `OutputSchemaContract`
- **Purpose**: Defines output schema constraints for prompts
- **Coverage**: Used by all evaluation and prompt operations
- **Core**: Yes
- **Enhanceable**: Low

### `mmap_optimizer/prompt/health.py`
- **Functions**: `check_prompt_health`, `safe_autofix_prompt_ir`
- **Issue Codes**: H1–H7 (duplicate section, missing render order, empty section, duplicate heading, frozen+compressible, schema not frozen, legacy large)
- **Coverage**: Tested via `test_pr7_contract_tests.py` (TestPromptHealthReportStructure, TestSafeAutofixPromptIR)
- **Core**: Yes
- **Enhanceable**: Could add more sophisticated checks (contradiction detection, coverage analysis)

### `mmap_optimizer/prompt/self_check.py`
- **Functions**: `self_check_prompt_text`
- **Issue Codes**: Undeclared placeholder, schema field not mentioned, contradictory output format rule
- **Coverage**: Tested via `test_prompt_quality_and_ab.py`
- **Core**: Yes
- **Enhanceable**: Could add more checks (example coverage, constraint completeness)

### `mmap_optimizer/prompt/standardizer.py`
- **Functions**: `normalize_markdown_spacing`, `unique_heading_titles`
- **Purpose**: Text normalization for raw prompts
- **Coverage**: Tested indirectly
- **Core**: Yes
- **Enhanceable**: Low

### `mmap_optimizer/prompt/refactor.py`
- **Functions**: `fix_ordered_list_numbering`
- **Purpose**: Fix malformed numbered lists in prompts
- **Coverage**: Tested via `test_llm_repair_semantic_and_prompt_tools.py`
- **Core**: Yes
- **Enhanceable**: Low

### `mmap_optimizer/prompt/ab_test.py`
- **Functions**: `run_prompt_ab_test`
- **Purpose**: A/B testing for prompt candidates
- **Coverage**: Tested via `test_prompt_quality_and_ab.py`
- **Core**: Yes
- **Enhanceable**: Could add statistical rigor

### `mmap_optimizer/prompt/version.py`
- **Classes**: `PromptVersion`
- **Purpose**: Version wrapper for PromptIR with lineage tracking
- **Coverage**: Tested indirectly
- **Core**: Yes
- **Enhanceable**: Low

## 3. Template Library

### `mmap_optimizer/templates/optimizer_prompts.py`
- **Templates**: 13 optimizer-specific prompt templates:
  1. `patch_text_match` - Map fuzzy locator to verbatim text
  2. `patch_translation` - Calibrate legacy patch locators
  3. `patch_translation_retry` - Retry failed patch calibration
  4. `json_fix` - Repair malformed JSON
  5. `patch_generation` - Generate patch candidates
  6. `patch_semantic_merge` - Merge related patches
  7. `patch_root_audit` - Audit patch consistency
  8. `section_rewrite` - Rewrite single section
  9. `llm_prune` - Prune section content
  10. `llm_prune_validation` - Validate pruned section
  11. `prompt_numbering_refactor` - Fix numbering
  12. `prompt_format_repair` - Normalize formatting
  13. `prompt_standardization` - Map raw to standard structure
  14. `prompt_self_check` - Quality audit
- **Coverage**: Some templates tested via integration tests
- **Core**: Yes
- **Enhanceable**: Could add more examples, stronger output contracts

### `mmap_optimizer/templates/registry.py`
- **Classes**: `PromptTemplateRegistry`
- **Purpose**: Template registration and lookup
- **Coverage**: Tested indirectly
- **Core**: Yes
- **Enhanceable**: Could add versioning, deprecation warnings

### `mmap_optimizer/templates/schema.py`
- **Classes**: `PromptTemplateSpec`
- **Purpose**: Typed template specification with input/output contracts
- **Coverage**: Tested indirectly
- **Core**: Yes
- **Enhanceable**: Could add validation, schema evolution

## 4. Evaluation and Optimization

### `mmap_optimizer/evaluation/evaluator.py`
- **Classes**: `Evaluator`, `EvaluationRecord`
- **Purpose**: Evaluate model outputs against ground truth
- **Coverage**: Tested via `test_prompt_evaluator.py`
- **Core**: Yes
- **Enhanceable**: Could add more nuanced scoring

### `mmap_optimizer/evaluation/prompt_optimizer.py`
- **Classes**: `EvaluationPromptOptimizer`, `EvalPromptBehaviorSuite`, `EvaluationCase`
- **Purpose**: Optimize evaluation prompts based on mismatch cases
- **Coverage**: Tested via `test_evaluation_prompt_optimizer.py`
- **Core**: Yes
- **Enhanceable**: Could add more sophisticated patch generation

## 5. Related Engines

### `mmap_optimizer/fewshot/engine.py`
- **Purpose**: Few-shot example optimization
- **Built-in Examples**: Simple Chinese reasoning text generation
- **Coverage**: Integration tested
- **Core**: Yes
- **Enhanceable**: Could add more sophisticated example selection

### `mmap_optimizer/compression/engine.py`
- **Purpose**: Line-budget compression with behavior preservation
- **Coverage**: Tested via `test_compression_risk_aware.py`
- **Core**: Yes
- **Enhanceable**: Could improve compression quality

## 6. Test Coverage Summary

| Module | Test File | Coverage |
|--------|-----------|----------|
| prompt/ir | test_prompt_evaluator.py | Indirect |
| prompt/initializer | test_prompt_evaluator.py | Direct |
| prompt/renderer | (none) | None |
| prompt/contract | test_prompt_evaluator.py | Indirect |
| prompt/health | test_pr7_contract_tests.py | Direct |
| prompt/self_check | test_prompt_quality_and_ab.py | Direct |
| prompt/standardizer | test_llm_repair... | Indirect |
| prompt/refactor | test_llm_repair... | Direct |
| prompt/ab_test | test_prompt_quality_and_ab.py | Direct |
| evaluation/evaluator | test_prompt_evaluator.py | Direct |
| evaluation/prompt_optimizer | test_evaluation_prompt_optimizer.py | Direct |
| templates/optimizer_prompts | test_llm_repair... | Partial |
| fewshot/engine | (none) | None |
| compression/engine | test_compression_risk_aware.py | Direct |

## 7. Prompt Section Mapping

### Extraction Sections (`EXTRACTION_SECTIONS`)
1. `role_definition` - Role and task scope
2. `task_definition` - Task description
3. `input_description` - Input expectations
4. `quality_criteria` - Quality standards
5. `visual_evidence_rules` - Evidence handling
6. `ambiguity_policy` - Uncertainty handling
7. `reasoning_constraints` - Reasoning rules
8. `format_compliance_policy` - Format requirements
9. `negative_cases` - Anti-patterns
10. `self_check` - Self-validation
11. `output_schema` - Output format (frozen)
12. `legacy_unmapped` - Unstructured content

### Analysis Sections (`ANALYSIS_SECTIONS`)
1. `role_definition` - Role and goal
2. `analysis_task` - Task description
3. `ground_truth_alignment` - GT comparison
4. `error_attribution_policy` - Error categorization
5. `prompt_section_attribution_policy` - Section attribution
6. `patch_generation_policy` - Patch generation
7. `patch_risk_policy` - Risk assessment
8. `schema_guard_policy` - Schema protection
9. `uncertainty_policy` - Uncertainty handling
10. `self_check` - Self-validation
11. `analysis_output_schema` - Output format (frozen)
12. `legacy_unmapped` - Unstructured content

## 8. Prompt Roles Classification

Based on the current codebase analysis:

| Role | Files | Prompt Type |
|------|-------|-------------|
| Extraction / Task | `prompts/raw/extraction.txt` | EXTRACTION |
| Analysis / Patch Generation | `prompts/raw/analysis.txt` | ANALYSIS |
| Patch Alignment | `templates/optimizer_prompts.py` | INTERNAL |
| JSON Repair | `templates/optimizer_prompts.py` | INTERNAL |
| Compression | `templates/optimizer_prompts.py` | INTERNAL |
| Evaluation | `mmap_optimizer/evaluation/evaluator.py` | INTERNAL |
| Few-shot Examples | `mmap_optimizer/fewshot/engine.py` | INTERNAL |
| System (Scenario) | `scenarios/default/prompts/system.md` | SCENARIO |
