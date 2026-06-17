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
