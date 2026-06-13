from __future__ import annotations

import json

from tests._compat import candidate_modules, find_symbol

ARTIFACT_MODULES = candidate_modules(
    "mmap.llm_artifacts",
    "mmap.artifacts",
    "mmap.semantic",
    "mmap_engine.llm_artifacts",
    "src.llm_artifacts",
)


def test_json_repair_emits_audit_artifact_for_invalid_but_repairable_json() -> None:
    repair_json = find_symbol(ARTIFACT_MODULES, "repair_json", "repair_llm_json", "json_repair")

    repaired, artifact = repair_json('{"answer": "yes", "score": 1,}', audit=True)

    assert repaired == {"answer": "yes", "score": 1}
    assert artifact["kind"] in {"json_repair", "llm_json_repair"}
    assert artifact["changed"] is True
    assert "trailing" in json.dumps(artifact).lower()


def test_semantic_merge_records_inputs_strategy_and_resolution() -> None:
    semantic_merge = find_symbol(ARTIFACT_MODULES, "semantic_merge", "merge_semantic_results")

    merged, artifact = semantic_merge(
        {"claim": "A", "confidence": 0.7},
        {"claim": "A", "evidence": ["doc-1"]},
        audit=True,
    )

    assert merged["claim"] == "A"
    assert merged["confidence"] == 0.7
    assert merged["evidence"] == ["doc-1"]
    assert artifact["kind"] == "semantic_merge"
    assert artifact["inputs"]
    assert artifact["resolution"]


def test_compression_audit_artifact_preserves_traceability() -> None:
    compress = find_symbol(ARTIFACT_MODULES, "compress_with_audit", "compress_context", "compress_artifact")

    compressed, artifact = compress(
        "Sentence one. Sentence two has the important fact. Sentence three.",
        max_chars=38,
        audit=True,
    )

    assert len(compressed) <= 38
    assert "important" in compressed
    assert artifact["kind"] in {"compression", "context_compression"}
    assert artifact["original_length"] > artifact["compressed_length"]
    assert artifact.get("hash") or artifact.get("source_hash")
