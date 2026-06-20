from __future__ import annotations

from mmap_optimizer.evaluation.evaluator import EvaluationRecord
from mmap_optimizer.patch.schema import Patch
from .patch_tester import PatchTestSuite


class PatchTestSuiteBuilder:
    def build_individual_suite(self, *, round_id: str, patch: Patch, current_evaluations: list[EvaluationRecord], max_samples: int = 48, canary_sample_ids: list[str] | None = None, historically_fixed_sample_ids: list[str] | None = None) -> PatchTestSuite:
        source = list(dict.fromkeys(patch.source_sample_ids))
        canary = [s for s in (canary_sample_ids or []) if s not in source]
        hist_fixed = [s for s in (historically_fixed_sample_ids or []) if s not in source and s not in set(canary)]
        excluded = set(source) | set(canary) | set(hist_fixed)
        correct = [e.sample_id for e in current_evaluations if e.overall_status == "correct" and e.sample_id not in excluded]
        wrong = [e.sample_id for e in current_evaluations if e.overall_status != "correct" and e.sample_id not in excluded]
        sample_ids = (source + canary + hist_fixed + correct + wrong)[:max_samples]
        return PatchTestSuite(
            id=f"suite_{round_id}_{patch.id}",
            round_id=round_id,
            sample_ids=sample_ids,
            suite_type="individual_patch",
            composition={
                "source_error": len([s for s in sample_ids if s in source]),
                "canary": len([s for s in sample_ids if s in set(canary)]),
                "historical_fixed": len([s for s in sample_ids if s in set(hist_fixed)]),
                "current_correct": len([s for s in sample_ids if s in set(correct)]),
            },
        )

    def build_bundle_suite(self, *, round_id: str, patches: list[Patch], current_evaluations: list[EvaluationRecord], max_samples: int = 96, canary_sample_ids: list[str] | None = None, historically_fixed_sample_ids: list[str] | None = None) -> PatchTestSuite:
        source: list[str] = []
        for patch in patches:
            source.extend(patch.source_sample_ids)
        source = list(dict.fromkeys(source))
        canary = [s for s in (canary_sample_ids or []) if s not in source]
        hist_fixed = [s for s in (historically_fixed_sample_ids or []) if s not in source and s not in set(canary)]
        excluded = set(source) | set(canary) | set(hist_fixed)
        correct = [e.sample_id for e in current_evaluations if e.overall_status == "correct" and e.sample_id not in excluded]
        wrong = [e.sample_id for e in current_evaluations if e.overall_status != "correct" and e.sample_id not in excluded]
        sample_ids = (source + canary + hist_fixed + correct + wrong)[:max_samples]
        bundle_id = "_".join(patch.id for patch in patches) or "empty"
        return PatchTestSuite(
            id=f"suite_{round_id}_bundle_{bundle_id}",
            round_id=round_id,
            sample_ids=sample_ids,
            suite_type="bundle_patch",
            composition={
                "source_error": len([s for s in sample_ids if s in source]),
                "canary": len([s for s in sample_ids if s in set(canary)]),
                "historical_fixed": len([s for s in sample_ids if s in set(hist_fixed)]),
                "current_correct": len([s for s in sample_ids if s in set(correct)]),
                "bundle_patch_count": len(patches),
            },
        )

    def build_toxic_suite(self, *, round_id: str, toxic_sample_ids: list[str], max_samples: int = 48) -> PatchTestSuite:
        """Build a test suite for toxic patch detection.

        Used in Step 6.4: after identifying "previously correct, now broken"
        samples, each candidate patch is re-applied individually and tested
        on this toxic sample set.
        """
        sample_ids = list(dict.fromkeys(toxic_sample_ids))[:max_samples]
        return PatchTestSuite(
            id=f"suite_{round_id}_toxic",
            round_id=round_id,
            sample_ids=sample_ids,
            suite_type="toxic_detection",
            composition={
                "toxic_sample_count": len(sample_ids),
            },
        )

    def build_analysis_test_suite(
        self,
        *,
        round_id: str,
        analysis_error_sample_ids: list[str],
        analysis_reflection_sample_ids: list[str] | None = None,
        max_samples: int = 48,
    ) -> PatchTestSuite:
        """Build a test suite for analysis prompt optimization.

        Used in Step 6 of analysis prompt optimization: collects samples
        where the analysis prompt made errors (blind evaluation mismatches)
        plus samples with reflection records for targeted testing.
        """
        error_ids = list(dict.fromkeys(analysis_error_sample_ids))
        reflection_ids = list(dict.fromkeys(analysis_reflection_sample_ids or []))
        combined = list(dict.fromkeys(error_ids + reflection_ids))[:max_samples]
        return PatchTestSuite(
            id=f"suite_{round_id}_analysis",
            round_id=round_id,
            sample_ids=combined,
            suite_type="analysis_prompt_test",
            composition={
                "analysis_error_count": len([s for s in combined if s in set(error_ids)]),
                "reflection_count": len([s for s in combined if s in set(reflection_ids)]),
                "total_samples": len(combined),
            },
        )
