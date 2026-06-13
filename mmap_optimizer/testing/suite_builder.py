from __future__ import annotations

from mmap_optimizer.evaluation.evaluator import EvaluationRecord
from mmap_optimizer.patch.schema import Patch
from .patch_tester import PatchTestSuite


class PatchTestSuiteBuilder:
    def build_individual_suite(self, *, round_id: str, patch: Patch, current_evaluations: list[EvaluationRecord], max_samples: int = 48) -> PatchTestSuite:
        source = list(dict.fromkeys(patch.source_sample_ids))
        correct = [e.sample_id for e in current_evaluations if e.overall_status == "correct" and e.sample_id not in source]
        wrong = [e.sample_id for e in current_evaluations if e.overall_status != "correct" and e.sample_id not in source]
        sample_ids = (source + correct + wrong)[:max_samples]
        return PatchTestSuite(
            id=f"suite_{round_id}_{patch.id}",
            round_id=round_id,
            sample_ids=sample_ids,
            suite_type="individual_patch",
            composition={"source_error": len(source), "current_correct": len(correct[: max(0, max_samples - len(source))])},
        )

    def build_bundle_suite(self, *, round_id: str, patches: list[Patch], current_evaluations: list[EvaluationRecord], max_samples: int = 96) -> PatchTestSuite:
        source: list[str] = []
        for patch in patches:
            source.extend(patch.source_sample_ids)
        source = list(dict.fromkeys(source))
        correct = [e.sample_id for e in current_evaluations if e.overall_status == "correct" and e.sample_id not in source]
        wrong = [e.sample_id for e in current_evaluations if e.overall_status != "correct" and e.sample_id not in source]
        sample_ids = (source + correct + wrong)[:max_samples]
        bundle_id = "_".join(patch.id for patch in patches) or "empty"
        return PatchTestSuite(
            id=f"suite_{round_id}_bundle_{bundle_id}",
            round_id=round_id,
            sample_ids=sample_ids,
            suite_type="bundle_patch",
            composition={
                "source_error": len(source),
                "current_correct": len(correct[: max(0, max_samples - len(source))]),
                "bundle_patch_count": len(patches),
            },
        )
