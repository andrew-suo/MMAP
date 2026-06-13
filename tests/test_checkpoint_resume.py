import json

from mmap_optimizer.cli import main
from mmap_optimizer.orchestration.checkpoint import load_checkpoint
from mmap_optimizer.orchestration.optimizer_loop import OptimizerLoop


def test_optimizer_writes_checkpoint_and_resume_continues_state(tmp_path):
    first = OptimizerLoop(run_dir=tmp_path, rounds=1).run()
    checkpoint_path = tmp_path / "checkpoint.json"

    assert first.completed_round_ids == ["round-0001"]
    assert checkpoint_path.exists()

    first_checkpoint = load_checkpoint(tmp_path)
    assert first_checkpoint.active_extraction_prompt.version == 2
    assert first_checkpoint.active_analysis_prompt.version == 2
    assert first_checkpoint.next_round_index == 2
    assert first_checkpoint.latest_metrics_summary["round_id"] == "round-0001"
    assert first_checkpoint.sample_states["round-0001"] == {"status": "completed"}

    second = OptimizerLoop(run_dir=tmp_path, rounds=1, resume=True).run()
    second_checkpoint = load_checkpoint(tmp_path)

    assert second.completed_round_ids == ["round-0001", "round-0002"]
    assert second_checkpoint.completed_round_ids == ["round-0001", "round-0002"]
    assert second_checkpoint.active_extraction_prompt.version == 3
    assert second_checkpoint.active_analysis_prompt.version == 3
    assert second_checkpoint.next_round_index == 3
    assert second_checkpoint.latest_metrics_summary["round_id"] == "round-0002"
    assert second_checkpoint.latest_metrics_summary["completed_round_count"] == 2
    assert set(second_checkpoint.sample_states) == {"round-0001", "round-0002"}


def test_cli_run_supports_resume(tmp_path, capsys):
    assert main(["run", "--run-dir", str(tmp_path), "--rounds", "1"]) == 0
    capsys.readouterr()

    assert main(["run", "--run-dir", str(tmp_path), "--rounds", "1", "--resume"]) == 0
    output = json.loads(capsys.readouterr().out)
    checkpoint = load_checkpoint(tmp_path)

    assert output["completed_round_ids"] == ["round-0001", "round-0002"]
    assert checkpoint.completed_round_ids == ["round-0001", "round-0002"]
    assert checkpoint.active_extraction_prompt.version == 3
    assert checkpoint.active_analysis_prompt.version == 3
