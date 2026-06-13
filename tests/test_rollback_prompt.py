import json

from mmap_optimizer.cli.main import active_prompt_path, main
from mmap_optimizer.prompt.snapshot import PromptVersion, save_prompt_snapshot


def read_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_rollback_prompt_to_output_path_matches_snapshot(tmp_path):
    run_dir = tmp_path / "run"
    snapshot = PromptVersion(
        id="prompt-123",
        version=7,
        content="Extract the fields exactly.",
        prompt_type="extraction",
    )
    save_prompt_snapshot(run_dir, "snapshot-a", "extraction", snapshot)

    output_path = tmp_path / "rolled-back.json"

    exit_code = main(
        [
            "rollback-prompt",
            "--run-dir",
            str(run_dir),
            "--snapshot-id",
            "snapshot-a",
            "--prompt-type",
            "extraction",
            "--output-path",
            str(output_path),
        ]
    )

    assert exit_code == 0
    restored = read_json(output_path)
    assert restored["id"] == snapshot.id
    assert restored["version"] == snapshot.version
    assert restored["content"] == snapshot.content


def test_rollback_prompt_to_active_prompt_updates_run_state(tmp_path):
    run_dir = tmp_path / "run"
    snapshot = PromptVersion(
        id="analysis-prompt",
        version=3,
        content="Analyze the extracted fields.",
        prompt_type="analysis",
    )
    save_prompt_snapshot(run_dir, "snapshot-b", "analysis", snapshot)

    exit_code = main(
        [
            "rollback-prompt",
            "--run-dir",
            str(run_dir),
            "--snapshot-id",
            "snapshot-b",
            "--prompt-type",
            "analysis",
        ]
    )

    assert exit_code == 0
    active_prompt = read_json(active_prompt_path(run_dir, "analysis"))
    assert active_prompt["id"] == snapshot.id
    assert active_prompt["version"] == snapshot.version
    assert active_prompt["content"] == snapshot.content

    run_state = read_json(run_dir / "run_state.json")
    assert run_state["stage"] == "rolled_back"
    assert run_state["rollback_snapshot_id"] == "snapshot-b"
