from __future__ import annotations

from tests._compat import candidate_modules, find_symbol

ROUND_MODULES = candidate_modules(
    "mmap.patch_and_round",
    "mmap.round",
    "mmap.pipeline",
    "mmap_engine.pipeline",
    "src.pipeline",
)


def test_patch_and_round_semantic_flags_smoke() -> None:
    run_round = find_symbol(ROUND_MODULES, "run_patch_and_round", "patch_and_round", "run_round")

    result = run_round(
        input_text="The answer is beta.",
        patch_operations=[
            {"op": "replace", "locator": {"text": "beta"}, "text": "gamma"},
        ],
        flags={"semantic_merge": True, "json_repair": True, "compression_audit": True},
    )

    assert result["text"] == "The answer is gamma."
    assert result.get("semantic_flags", {}).get("semantic_merge") is True
    assert any(artifact["kind"] in {"semantic_merge", "json_repair", "compression"} for artifact in result["artifacts"])
