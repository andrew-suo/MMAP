from __future__ import annotations

from enum import Enum


class PromptType(str, Enum):
    EXTRACTION = "extraction"
    ANALYSIS = "analysis"


class PromptVersionType(str, Enum):
    INITIAL = "initial"
    OPTIMIZATION = "optimization"
    COMPRESSION = "compression"
    ANALYSIS_SHADOW_PROMOTION = "analysis_shadow_promotion"
    FEW_SHOT_OPTIMIZATION = "few_shot_optimization"
    MANUAL = "manual"


class PatchStatus(str, Enum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    MERGED = "merged"
    TESTING = "testing"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"


class RunType(str, Enum):
    EXTRACTION = "extraction"
    ANALYSIS = "analysis"
    PATCH_TEST_EXTRACTION = "patch_test_extraction"
    DYNAMIC_VALIDATION_EXTRACTION = "dynamic_validation_extraction"
    ANALYSIS_SHADOW_CURRENT = "analysis_shadow_current"
    ANALYSIS_SHADOW_CANDIDATE = "analysis_shadow_candidate"
    COMPRESSION_BEHAVIOR_TEST = "compression_behavior_test"


class EvaluationStatus(str, Enum):
    CORRECT = "correct"
    WRONG = "wrong"
    SCHEMA_ERROR = "schema_error"
    PARSE_ERROR = "parse_error"


class Transition(str, Enum):
    FIXED = "fixed"
    BROKEN = "broken"
    UNCHANGED_WRONG = "unchanged_wrong"
    UNCHANGED_CORRECT = "unchanged_correct"
    CHANGED_BUT_STILL_CORRECT = "changed_but_still_correct"
