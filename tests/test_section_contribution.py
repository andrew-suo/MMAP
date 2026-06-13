import json

import pytest

from mmap_optimizer.compression.engine import CompressionEngine
from mmap_optimizer.metrics.section_contribution import (
    EMA_FILENAME,
    SectionContribution,
    SectionContributionEMAStore,
)
from mmap_optimizer.patches.tree_reduce_patch_merger import PatchCandidate, TreeReducePatchMerger
from mmap_optimizer.prompts.artifact import PromptSection, attach_section_scores
from mmap_optimizer.runners.analysis_runner import AnalysisRunner
from mmap_optimizer.runners.patch_generation_runner import PatchGenerationRunner
from mmap_optimizer.sampling.section_sampler import rank_sections_for_sampling


def test_section_contribution_ema_persists_across_rounds(tmp_path):
    store = SectionContributionEMAStore(tmp_path, alpha=0.5)
    first = store.update([SectionContribution(section_id="rules", score=-0.8, cited=0.9, parasite=0.8, accuracy=0.2)])
    assert first["rules"].ema_score == -0.8

    second = SectionContributionEMAStore(tmp_path, alpha=0.5).update(
        [SectionContribution(section_id="rules", score=0.2, cited=0.9, parasite=0.6, accuracy=0.6)]
    )
    assert second["rules"].ema_score == pytest.approx(-0.3)

    saved = json.loads((tmp_path / EMA_FILENAME).read_text())
    assert saved["rules"]["ema_score"] == pytest.approx(-0.3)


def test_high_risk_sections_are_added_to_runner_context(tmp_path):
    SectionContributionEMAStore(tmp_path).update(
        [
            SectionContribution.from_metrics("bad", cited=0.95, parasite=0.9, accuracy=0.1),
            SectionContribution.from_metrics("good", cited=0.2, parasite=0.0, accuracy=1.0),
        ]
    )

    analysis_context = AnalysisRunner(tmp_path).build_input_context({})
    patch_context = PatchGenerationRunner(tmp_path).build_input_context({})

    assert analysis_context["high_risk_sections"][0]["section_id"] == "bad"
    assert patch_context["high_risk_sections"][0]["section_id"] == "bad"


def test_negative_contribution_affects_sampling_patch_and_compression_ordering():
    risky_safe = PatchCandidate(
        patch_id="safe-risky",
        section_id="risk",
        content="guard critical rule",
        cited=0.95,
        parasite=0.9,
        accuracy=0.1,
        safe=True,
        score=0.1,
    )
    high_score_unsafe = PatchCandidate(
        patch_id="unsafe-benign",
        section_id="benign",
        content="rewrite",
        cited=0.1,
        parasite=0.0,
        accuracy=1.0,
        safe=False,
        score=10.0,
    )

    sampling = rank_sections_for_sampling([
        {"section_id": "healthy", "score": 0.5, "risk_score": 0.0},
        {"section_id": "negative", "score": -0.7, "risk_score": 0.4},
    ])
    assert [section.section_id for section in sampling] == ["negative", "healthy"]

    merged = TreeReducePatchMerger(max_patches=1).merge([high_score_unsafe, risky_safe])
    assert [patch.patch_id for patch in merged] == ["safe-risky"]

    compression = CompressionEngine().sort_candidates(
        [
            {"section_id": "risk", "tokens": 500, "metrics": {"score": -0.7, "risk_score": 0.9}},
            {"section_id": "benign", "tokens": 480, "metrics": {"score": 0.0, "risk_score": 0.0}},
        ]
    )
    assert [candidate.section_id for candidate in compression] == ["benign", "risk"]


def test_prompt_sections_carry_section_scores():
    sections = [PromptSection("rules", "Do the thing")]
    contribution = SectionContribution.from_metrics("rules", cited=1.0, parasite=0.5, accuracy=0.5)

    attach_section_scores(sections, {"rules": contribution})

    assert sections[0].metrics["section_contribution"]["section_id"] == "rules"
    assert "section_score" in sections[0].metrics
