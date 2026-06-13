from dataclasses import dataclass, field
from datetime import datetime, timezone
import json

from mmap_optimizer.metrics.section_contribution import (
    aggregate_section_contributions,
    rank_compression_candidates,
    score_patch_merge_candidate,
    write_section_contribution_artifact,
)


@dataclass
class PromptSection:
    id: str
    metrics: dict = field(default_factory=dict)


def test_section_weight_increases_after_repeated_fixes(tmp_path):
    prompt_section = PromptSection(id="examples")

    section_metrics = aggregate_section_contributions(
        patch_test_results=[
            {"section_id": "examples", "fixed_count": 1, "accepted": True},
            {"section_id": "examples", "fixed_count": 2, "status": "merged"},
        ],
        compression_reports=[{"section_id": "examples", "status": "accepted"}],
        few_shot_reports=[{"section_id": "examples", "successes": ["a", "b"]}],
        prompt_sections=[prompt_section],
        now=datetime(2026, 6, 13, tzinfo=timezone.utc),
    )

    metrics = section_metrics["examples"]
    assert metrics["fixed_count"] == 5
    assert metrics["broken_count"] == 0
    assert metrics["net_gain"] == 5
    assert metrics["patch_accept_rate"] > 0
    assert metrics["contribution_weight"] > 1.0
    assert prompt_section.metrics["contribution_weight"] == metrics["contribution_weight"]

    artifact_path = write_section_contribution_artifact(section_metrics, tmp_path)
    assert artifact_path.name == "section_contribution.json"
    assert json.loads(artifact_path.read_text())["examples"]["fixed_count"] == 5

    patch_score = score_patch_merge_candidate(
        {"section_id": "examples", "score": 1.0}, section_metrics
    )
    ranked = rank_compression_candidates(
        [{"section_id": "examples", "score": 1.0}], section_metrics
    )
    assert patch_score > 1.0
    assert ranked[0]["weighted_score"] > 1.0


def test_section_weight_drops_after_broken_and_toxic_patch():
    baseline = aggregate_section_contributions(
        patch_test_results=[{"section_id": "safety", "fixed_count": 3, "accepted": True}],
        now=datetime(2026, 6, 13, tzinfo=timezone.utc),
    )
    degraded = aggregate_section_contributions(
        patch_test_results=[
            {"section_id": "safety", "fixed_count": 3, "accepted": True},
            {"section_id": "safety", "broken_count": 2, "toxicity_count": 2, "accepted": False},
        ],
        compression_reports=[{"section_id": "safety", "status": "rejected"}],
        now=datetime(2026, 6, 13, tzinfo=timezone.utc),
    )

    assert degraded["safety"]["broken_count"] == 2
    assert degraded["safety"]["toxicity_count"] == 2
    assert degraded["safety"]["compression_reject_rate"] == 1.0
    assert degraded["safety"]["contribution_weight"] < baseline["safety"]["contribution_weight"]
