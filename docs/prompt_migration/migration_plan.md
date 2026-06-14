# Prompt Migration Plan

This document outlines a phased approach to absorbing old project prompts into the current MMAP system. Each phase focuses on a specific goal with clear deliverables, risks, and acceptance criteria.

## Phase Overview

| Phase | Goal | Duration | Risk | Default behavior change |
|-------|------|----------|------|------------------------|
| 1 | Inventory | 1 week | None | None |
| 2 | Pattern Library | 2 weeks | Low | None |
| 3 | One Prompt Upgrade | 1 week | Medium | Per-scenario only |
| 4 | Scenario-gated Rollout | 2 weeks | Medium | Scenario-gated |
| 5 | Default Adoption | Ongoing | High | Yes (after validation) |

## Phase 1: Inventory Only

### Goal
Create a complete inventory of old project prompts and their capabilities.

### Deliverables
- Old prompt files in `docs/prompt_migration/source_prompts/`
- Capability mapping table completed in `prompt_absorption_strategy.md`
- Priority ranking for migration

### User Actions Required
1. Place old prompt files in `docs/prompt_migration/source_prompts/`
2. Organize by category (extraction, analysis, evaluation, etc.)
3. Note any context about each prompt's purpose and history

### Modified Files
- `docs/prompt_migration/source_prompts/` (new directory)
- `docs/prompt_migration/prompt_absorption_strategy.md` (updated mapping table)

### Testing
- Verify docs structure is correct
- No code changes, no behavior changes

### Risk
- None

### Default Behavior Change
- **No**

---

## Phase 2: Pattern Library

### Goal
Extract reusable patterns from old prompts and create a pattern library.

### Deliverables
- Pattern library in `mmap_optimizer/prompt/patterns/` (new module)
- Pattern documentation in `docs/prompt_migration/patterns/`
- Pattern tests in `tests/test_prompt_patterns.py`

### Pattern Library Structure
```
mmap_optimizer/prompt/patterns/
├── __init__.py
├── role_definition.py      # Role definition patterns
├── task_boundary.py        # Task boundary patterns
├── input_contract.py       # Input contract patterns
├── output_schema.py        # Output schema patterns
├── decision_rules.py       # Decision rule patterns
├── error_handling.py       # Error handling patterns
├── self_check.py           # Self-check patterns
├── fewshot_examples.py     # Few-shot example patterns
├── negative_examples.py    # Negative example patterns
├── compliance_rules.py     # Compliance rule patterns
├── evidence_patterns.py    # Evidence/citation patterns
└── evaluation_scoring.py   # Evaluation scoring patterns
```

### Pattern Interface
```python
@dataclass
class PromptPattern:
    """Base class for all prompt patterns."""
    id: str
    name: str
    description: str
    category: PatternCategory
    examples: list[str]  # Example implementations
    applicability: list[str]  # Which sections can use this
    risk_level: RiskLevel
    test_required: bool
    test_cases: list[PatternTestCase]

    def apply(self, section: PromptSection) -> PromptSection:
        """Apply pattern to a section."""
        ...

    def validate(self, section: PromptSection) -> ValidationResult:
        """Validate pattern application."""
        ...
```

### Modified Files
- `mmap_optimizer/prompt/patterns/` (new module)
- `docs/prompt_migration/patterns/` (new docs)
- `tests/test_prompt_patterns.py` (new test file)

### Testing
- Pattern extraction tests
- Pattern application tests
- Pattern validation tests

### Risk
- Low - patterns are additive, no default changes

### Default Behavior Change
- **No** - pattern library is opt-in

---

## Phase 3: One Prompt Upgrade

### Goal
Select one low-risk prompt area and enhance it using pattern library.

### Candidate Areas
1. **Evaluation Prompt** (lowest risk) - Enhance scoring criteria
2. **Repair Prompt** (low risk) - Enhance error recovery patterns
3. **Analysis Prompt** (medium risk) - Enhance patch generation
4. **Extraction Prompt** (highest risk) - Core prompt changes

### Recommendation
Start with **Evaluation Prompt** because:
- Evaluation affects quality assessment, not core extraction
- Easy to measure improvement via existing metrics
- Low risk of breaking existing functionality

### Deliverables
- Enhanced evaluation prompt patterns
- Pattern integration tests
- A/B test setup for validation

### Modified Files
- `mmap_optimizer/evaluation/evaluator.py` (minor enhancements)
- `mmap_optimizer/evaluation/prompt_optimizer.py` (enhanced patterns)
- `tests/test_prompt_evaluator.py` (enhanced tests)

### Testing
- Existing tests continue to pass
- New pattern-specific tests
- A/B test validation

### Risk
- Medium - evaluation prompt changes

### Default Behavior Change
- **No** - enhanced via prompt optimizer, not default

---

## Phase 4: Scenario-gated Rollout

### Goal
Enable enhanced prompts via explicit scenario configuration.

### Deliverables
- Scenario config option for enhanced prompts
- Migration guide for scenarios
- Validation tests for scenario prompts

### Scenario Config Example
```yaml
# scenarios/enhanced/scenario.yaml
prompt_config:
  use_enhanced_patterns: true
  pattern_version: "1.0"
  enabled_patterns:
    - role_definition_v2
    - self_check_extended
    - negative_examples_comprehensive
  disabled_patterns: []
```

### Modified Files
- `mmap_optimizer/core/scenario.py` (prompt config support)
- `scenarios/enhanced/` (new scenario)
- `docs/prompt_migration/scenario_guide.md`

### Testing
- Scenario loading tests
- Pattern application tests
- Smoke tests with enhanced scenario

### Risk
- Medium - scenario isolation prevents default impact

### Default Behavior Change
- **No** - requires explicit scenario selection

---

## Phase 5: Default Adoption

### Goal
Promote enhanced prompts to default after validation.

### Prerequisites
- All Phase 3 tests pass
- Phase 4 scenario validated
- No regression in smoke tests
- A/B test shows improvement

### Deliverables
- Enhanced prompts become default
- Migration documentation for users
- Rollback plan

### Modified Files
- `prompts/raw/extraction.txt` (enhanced)
- `prompts/raw/analysis.txt` (enhanced)
- `configs/optimizer.yaml` (updated defaults)

### Testing
- Full test suite
- Smoke tests
- A/B comparison
- Regression tests

### Risk
- High - changes default behavior

### Default Behavior Change
- **Yes** - requires validation before adoption

---

## Prompt Evaluation Criteria

Before migrating each pattern, evaluate against these criteria:

### 1. Output Format Stability
- **Definition**: Outputs consistently follow the specified schema
- **How to test**: Run 100+ samples, measure schema compliance
- **Pass condition**: >99% valid outputs

### 2. Task Boundary Respect
- **Definition**: Model stays within task scope, doesn't over-extend
- **How to test**: Provide out-of-scope inputs, measure refusal rate
- **Pass condition**: >95% appropriate refusals

### 3. Patch Applicability
- **Definition**: Generated patches can be applied to prompts
- **How to test**: Apply patches to prompts, measure success rate
- **Pass condition**: >90% successful application

### 4. Repair Recoverability
- **Definition**: Failed operations can be repaired
- **How to test**: Measure repair success rate on known failures
- **Pass condition**: >80% repair success

### 5. Compression Safety
- **Definition**: Compressed prompts preserve meaning and compliance
- **How to test**: Compare pre/post compression quality
- **Pass condition**: No quality regression >5%

### 6. Evaluation Consistency
- **Definition**: Evaluation results are stable across runs
- **How to test**: Run evaluation multiple times, measure variance
- **Pass condition**: <5% variance in scores

### 7. Artifact Trackability
- **Definition**: Prompt versions and changes are trackable
- **How to test**: Verify version history completeness
- **Pass condition**: 100% version tracking

### 8. Regression Risk
- **Definition**: Changes don't break existing functionality
- **How to test**: Full test suite before/after
- **Pass condition**: All existing tests pass

### 9. Smoke Behavior
- **Definition**: run-smoke continues to work correctly
- **How to test**: Run smoke test with new prompts
- **Pass condition**: Smoke test passes

### 10. Test Capture
- **Definition**: Issues are caught by existing tests
- **How to test**: Run test suite, measure coverage
- **Pass condition**: >80% pattern coverage

### Evaluation Score Table

| Metric | Weight | Pass | Warning | Fail |
|--------|--------|------|---------|------|
| Output Format Stability | 20% | >99% | 95-99% | <95% |
| Task Boundary Respect | 15% | >95% | 90-95% | <90% |
| Patch Applicability | 15% | >90% | 80-90% | <80% |
| Repair Recoverability | 10% | >80% | 70-80% | <70% |
| Compression Safety | 10% | <5% loss | 5-10% loss | >10% loss |
| Evaluation Consistency | 10% | <5% var | 5-10% var | >10% var |
| Artifact Trackability | 5% | 100% | 90-99% | <90% |
| Regression Risk | 10% | 0 failures | 1-2 failures | >2 failures |
| Smoke Behavior | 5% | Pass | - | Fail |
| **Total** | 100% | >85% | 70-85% | <70% |

---

## Deferred Items

The following are explicitly **NOT** part of this migration plan:

- Prompt rewrite for default prompts (handled in Phase 5)
- Direct import of old prompts (patterns only, not text)
- External model calls for prompt optimization
- Large-scale prompt testing infrastructure
- Prompt versioning system (exists in `prompt/version.py`)
- Prompt A/B testing at scale (exists but needs enhancement)

---

## Next Steps

### Immediate (This PR)
1. User provides old prompt files in `docs/prompt_migration/source_prompts/`
2. User reviews and completes capability mapping table
3. User prioritizes patterns for migration

### Phase 1 (Next Sprint)
1. Organize old prompts by category
2. Complete capability inventory
3. Create initial pattern library structure

### Phase 2 (Following Sprint)
1. Implement pattern extraction
2. Create pattern tests
3. Document patterns

### Phase 3 (Following Sprint)
1. Select upgrade target (recommend evaluation prompt)
2. Implement pattern integration
3. Validate with A/B testing
