# Prompt Absorption Strategy

This document describes how to absorb capabilities from old project prompts into the current MMAP prompt system without direct one-to-one mapping. The approach focuses on **capability modules** (patterns) rather than text reuse.

## 1. Overview

Old project prompts often contain sophisticated patterns that evolved over time. Rather than copying text verbatim, we extract the **underlying capabilities** and implement them as reusable modules that can enhance the current system.

### Key Principles
1. **Pattern over Text**: Extract structural patterns, not raw content
2. **Capability Mapping**: Match capabilities to existing modules, not prompts to prompts
3. **Safe Integration**: All integrations go through existing extension points
4. **Testable**: Each enhancement has clear acceptance criteria
5. **Reversible**: Changes can be rolled back without breaking core functionality

## 2. Prompt Capability Modules

The following modules represent reusable patterns that can be absorbed from old prompts:

### 2.1 Role Definition Pattern
- **Goal**: Provide clear, constrained role definition that prevents role creep
- **Current Target**: `role_definition` section in extraction/analysis prompts
- **Test Needed**: Yes - test role scope enforcement
- **Risk**: Low
- **Notes**: Current extraction prompt has good role definition but lacks explicit scope boundaries

### 2.2 Task Boundary Pattern
- **Goal**: Clearly delimit task scope, explicitly excluding out-of-scope content
- **Current Target**: `task_definition` section
- **Test Needed**: Yes - test boundary enforcement
- **Risk**: Low
- **Notes**: Current prompts mention boundaries but could be more explicit

### 2.3 Input Contract Pattern
- **Goal**: Define what inputs are expected and how to handle missing/ambiguous inputs
- **Current Target**: `input_description` section, `ambiguity_policy` section
- **Test Needed**: Yes - test ambiguity handling
- **Risk**: Medium - could change behavior for edge cases
- **Notes**: Current prompts have ambiguity policy but could be more comprehensive

### 2.4 Output Schema Pattern
- **Goal**: Ensure output schema is clear, complete, and consistent with task requirements
- **Current Target**: `output_schema` / `analysis_output_schema` sections
- **Test Needed**: Yes - test schema compliance
- **Risk**: Medium - schema changes affect downstream processing
- **Notes**: Already frozen in current system, pattern improvements go to validation

### 2.5 Decision Rule Pattern
- **Goal**: Encode decision logic in a clear, auditable format
- **Current Target**: `quality_criteria` / `reasoning_constraints` sections
- **Test Needed**: Yes - test rule application
- **Risk**: Medium - rule changes affect extraction behavior
- **Notes**: Current prompts use natural language; could adopt structured rule format

### 2.6 Error Handling Pattern
- **Goal**: Define how to handle errors, edge cases, and fallback scenarios
- **Current Target**: `ambiguity_policy` section, `uncertainty_policy` in analysis
- **Test Needed**: Yes - test error recovery
- **Risk**: Medium - could change error handling behavior
- **Notes**: Current prompts have some error handling but lack systematic approach

### 2.7 Self-check Pattern
- **Goal**: Prompt the model to verify its own output before returning
- **Current Target**: `self_check` section
- **Test Needed**: Yes - test self-check effectiveness
- **Risk**: Low
- **Notes**: Current system has `prompt/self_check.py` for static analysis; runtime self-check could be added

### 2.8 Few-shot Example Pattern
- **Goal**: Provide high-quality examples that illustrate correct behavior
- **Current Target**: `mmap_optimizer/fewshot/engine.py`
- **Test Needed**: Yes - test example quality and coverage
- **Risk**: Medium - examples affect model behavior
- **Notes**: Current system generates examples from ground truth; could enhance with curated examples

### 2.9 Negative Example Pattern
- **Goal**: Explicitly show what NOT to do
- **Current Target**: `negative_cases` section
- **Test Needed**: Yes - test anti-pattern enforcement
- **Risk**: Low
- **Notes**: Current prompts have `negative_cases` section but could be more comprehensive

### 2.10 Compliance / Safety Rule Pattern
- **Goal**: Ensure outputs comply with safety, ethical, and quality requirements
- **Current Target**: `format_compliance_policy`, `schema_guard_policy`
- **Test Needed**: Yes - test compliance enforcement
- **Risk**: Medium
- **Notes**: Current system has some compliance checks but could be more comprehensive

### 2.11 Evidence / Citation Pattern
- **Goal**: Require outputs to cite supporting evidence
- **Current Target**: `visual_evidence_rules`, `evidence` field in extraction output
- **Test Needed**: Yes - test evidence citation
- **Risk**: Low
- **Notes**: Current extraction prompt requires evidence but could enhance citation format

### 2.12 Repair / Retry Pattern
- **Goal**: Define how to handle failed operations and retries
- **Current Target**: `patch_translation_retry` template, `mmap_optimizer/patch/repair.py`
- **Test Needed**: Yes - test repair effectiveness
- **Risk**: Medium
- **Notes**: Current system has repair capabilities; could enhance with more patterns

### 2.13 Compression / Summarization Pattern
- **Goal**: Preserve core meaning while reducing verbosity
- **Current Target**: `llm_prune` template, `mmap_optimizer/compression/engine.py`
- **Test Needed**: Yes - test semantic preservation
- **Risk**: Medium - compression could lose important details
- **Notes**: Current system has compression; could enhance with better preservation patterns

### 2.14 Evaluation / Scoring Pattern
- **Goal**: Provide clear evaluation criteria and scoring rubrics
- **Current Target**: `mmap_optimizer/evaluation/evaluator.py`
- **Test Needed**: Yes - test evaluation consistency
- **Risk**: Medium
- **Notes**: Current evaluator is rule-based; could enhance with more nuanced scoring

### 2.15 Structured JSON Output Pattern
- **Goal**: Ensure outputs are valid, well-structured JSON
- **Current Target**: `output_schema` section, `json_fix` template
- **Test Needed**: Yes - test JSON validity
- **Risk**: Low
- **Notes**: Current system has `json_fix` template; could enhance robustness

## 3. Mapping Strategy

The following table shows how old prompt capabilities map to the current system. **Note**: This table is speculative and requires user input to fill in the "Old prompt capability" column.

| Old prompt capability | Current target | Absorption mode | Risk | Test needed | Notes |
| --------------------- | -------------- | --------------- | ---- | ----------- | ----- |
| *Awaiting user input* | - | - | - | - | User to provide old prompts |
| Role scope definition | `role_definition` section | rewrite_as_pattern | Low | Yes | Extract pattern, integrate via section enhancement |
| Multi-step workflow | `task_definition` section | extract_rule_only | Low | Yes | Identify workflow patterns, add to section |
| Evidence citation format | Extraction output, `evidence` field | extract_example_only | Low | Yes | Add structured evidence format to section |
| Ambiguity handling | `ambiguity_policy` section | rewrite_as_pattern | Medium | Yes | Enhance existing policy with comprehensive patterns |
| Edge case coverage | Multiple sections | extract_rule_only | Medium | Yes | Identify edge cases, add as rules |
| Self-verification steps | `self_check` section | rewrite_as_pattern | Low | Yes | Add systematic self-check pattern |
| Negative examples | `negative_cases` section | rewrite_as_pattern | Low | Yes | Enhance with more anti-patterns |
| Confidence scoring | Extraction output, `confidence` field | extract_schema_only | Medium | Yes | Document schema, enhance if needed |
| Error recovery | `uncertainty_policy` in analysis | extract_rule_only | Medium | Yes | Identify recovery patterns |
| Compliance rules | `format_compliance_policy` | rewrite_as_pattern | Medium | Yes | Extract and formalize rules |
| Few-shot example format | `fewshot/engine.py` | extract_example_only | Medium | Yes | Document format, enhance generation |
| JSON validation | `output_schema`, `json_fix` | do_not_use | Low | Yes | Current system is sufficient |
| Patch generation strategy | Analysis prompt, templates | rewrite_as_pattern | Medium | Yes | Enhance templates with strategies |
| Semantic merge strategy | `patch_semantic_merge` template | rewrite_as_pattern | Medium | Yes | Document and enhance patterns |

## 4. Integration Points

The current system provides the following extension points for prompt enhancements:

### 4.1 Section-based Enhancement
- **Location**: `mmap_optimizer/prompt/initializer.py`
- **Method**: Add content to predefined sections via `EXTRACTION_SECTIONS` or `ANALYSIS_SECTIONS`
- **Risk**: Low - existing sections are extended, not replaced

### 4.2 New Section Addition
- **Location**: `mmap_optimizer/prompt/initializer.py`
- **Method**: Add new section IDs to `EXTRACTION_SECTIONS` or `ANALYSIS_SECTIONS`
- **Risk**: Medium - new sections require rendering and health checks

### 4.3 Template Enhancement
- **Location**: `mmap_optimizer/templates/optimizer_prompts.py`
- **Method**: Add examples, enhance output contracts
- **Risk**: Medium - template changes affect patch generation behavior

### 4.4 Scenario-based Prompts
- **Location**: `scenarios/*/prompts/`
- **Method**: Create scenario-specific prompts without affecting defaults
- **Risk**: Low - scenarios are isolated

### 4.5 Health Check Enhancement
- **Location**: `mmap_optimizer/prompt/health.py`
- **Method**: Add new issue codes for new patterns
- **Risk**: Low - health checks are additive

### 4.6 Self-Check Enhancement
- **Location**: `mmap_optimizer/prompt/self_check.py`
- **Method**: Add new check types for new patterns
- **Risk**: Low - self-checks are additive

## 5. User Input Required

To complete this strategy, users need to provide:

1. **Old Prompt Files**: Place old project prompts in `docs/prompt_migration/source_prompts/`
2. **Capability Identification**: Review the mapping table and fill in old capabilities
3. **Priority Ranking**: Indicate which capabilities are most valuable
4. **Test Data**: Provide example inputs/outputs for new capability tests

## 6. Migration Entry Points

Users can place old prompt materials in the following locations:

```
docs/prompt_migration/
├── source_prompts/          # Place old prompt files here
│   ├── extraction/
│   │   ├── system_prompts/
│   │   ├── task_prompts/
│   │   └── evaluation_prompts/
│   └── analysis/
│       ├── patch_generation/
│       └── evaluation/
├── current_prompt_inventory.md
├── prompt_absorption_strategy.md
└── migration_plan.md
```
