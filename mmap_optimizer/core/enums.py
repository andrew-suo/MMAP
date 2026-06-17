from __future__ import annotations

from enum import Enum


class PromptType(str, Enum):
    EXTRACTION = "extraction"
    ANALYSIS = "analysis"


class PromptVersionType(str, Enum):
    INITIAL = "initial"
    OPTIMIZATION = "optimization"
    COMPRESSION = "compression"
    ANALYSIS_SHADOW_PROMOTION = "analysis_shadow_promotion"  # Reserved for future analysis shadow promotion
    FEW_SHOT_OPTIMIZATION = "few_shot_optimization"
    MANUAL = "manual"  # Reserved for future manual prompt management


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
    DYNAMIC_VALIDATION_EXTRACTION = "dynamic_validation_extraction"
    ANALYSIS_SHADOW_CURRENT = "analysis_shadow_current"
    ANALYSIS_SHADOW_CANDIDATE = "analysis_shadow_candidate"
    COMPRESSION_BEHAVIOR_TEST = "compression_behavior_test"
    FEW_SHOT_TEST = "few_shot_test"
    REGRESSION_CHECK = "regression_check"


class EvaluationStatus(str, Enum):
    CORRECT = "correct"
    WRONG = "wrong"
    SCHEMA_ERROR = "schema_error"
    PARSE_ERROR = "parse_error"


# String constants for PatchStatus (for compatibility with code that uses bare strings)
PATCH_STATUS_DRAFT = "draft"
PATCH_STATUS_CANDIDATE = "candidate"
PATCH_STATUS_MERGED = "merged"
PATCH_STATUS_TESTING = "testing"
PATCH_STATUS_ACCEPTED = "accepted"
PATCH_STATUS_REJECTED = "rejected"
PATCH_STATUS_QUARANTINED = "quarantined"
PATCH_STATUS_SUPERSEDED = "superseded"
PATCH_STATUS_ROLLED_BACK = "rolled_back"


class Transition(str, Enum):
    FIXED = "fixed"
    BROKEN = "broken"
    UNCHANGED_WRONG = "unchanged_wrong"
    UNCHANGED_CORRECT = "unchanged_correct"
