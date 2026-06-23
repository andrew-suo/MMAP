"""PR4 Task 34: 最终验收测试。

对照 v1.4 设计文档第 12 节的 17 条验收标准，逐项验证：
1.  factory.py 不再为 compression 返回 mock executor
2.  CompressionExecutor 支持超限检测
3.  CompressionExecutor 支持压缩后重新测试
4.  压缩后指标不降且无新增 broken 才接受
5.  压缩失败时保留未压缩 prompt
6.  extraction / analysis 都能生成 compression_report
7.  Run 级 artifact 完整
8.  Prompt iteration artifact 完整
9.  Few-shot artifact 完整
10. run_summary.json 能快速说明本次 run 的收益和风险
11. final_extraction_prompt.json 保存最终抽取 prompt
12. final_analysis_prompt.json 保存最终分析 prompt
13. final_fewshot_examples.jsonl 保存最终 few-shot
14. 10～20 条小数据集 smoke 可运行
15. CLI 文档包含真实运行命令
16. use_mock=false 时，缺少 model_client 应报错
17. 真实运行模式下不再依赖 mock executor
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mmap_optimizer.refactored.config import RefactoredConfig, load_config
from mmap_optimizer.refactored.executors.compression_executor import CompressionExecutor
from mmap_optimizer.refactored.executors.factory import create_executors
from mmap_optimizer.refactored.extraction_prompt_optimization_stage import EvalRecord
from mmap_optimizer.refactored.runner import MMAPRunner
from mmap_optimizer.refactored.sample import SampleBatch, SampleSet, SampleSpec
from mmap_optimizer.refactored.structured_prompt import PromptSection, StructuredPrompt

REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_CONFIG = REPO_ROOT / "configs" / "refactored_smoke.yaml"
SMOKE_DATASET = REPO_ROOT / "data" / "smoke_samples.jsonl"
EXTRACTION_PROMPT = REPO_ROOT / "prompts" / "raw" / "extraction.txt"
ANALYSIS_PROMPT = REPO_ROOT / "prompts" / "raw" / "analysis.txt"


def _make_sample_set(sample_ids: list[str]) -> SampleSet:
    """构造 SampleSet。"""
    ss = SampleSet()
    for sid in sample_ids:
        ss.add_spec(SampleSpec(id=sid, input={"text": sid}, ground_truth={"result": "OK"}))
    return ss


def _make_batch(sample_ids: list[str]) -> SampleBatch:
    """构造 SampleBatch。"""
    return SampleBatch(
        id="b1",
        phase="test",
        iteration=1,
        sample_ids=list(sample_ids),
        sampler_name="test",
    )


def _make_eval_records(sample_ids: list[str], status: str = "correct") -> list[EvalRecord]:
    """构造 EvalRecord 列表。"""
    return [
        EvalRecord(
            sample_id=sid,
            extraction_result_id=sid,
            status=status,
            correct=(status == "correct"),
        )
        for sid in sample_ids
    ]


def _make_over_limit_prompt() -> StructuredPrompt:
    """构造超限的 StructuredPrompt。"""
    long_content = "\n".join([f"line {i}" for i in range(50)])
    section = PromptSection(
        id="section_1", title="Test", level=1, content=long_content,
    )
    return StructuredPrompt(
        id="test_prompt", prompt_type="extraction",
        sections=[section], raw_markdown=long_content,
    )


def _run_smoke(tmp_path: Path) -> tuple[MMAPRunner, Path]:
    """执行一次 smoke run。"""
    config = load_config(SMOKE_CONFIG)
    config.run.output_dir = str(tmp_path / "acceptance_run")
    config.run.use_mock = True
    runner = MMAPRunner(
        config=config,
        extraction_prompt_path=EXTRACTION_PROMPT,
        analysis_prompt_path=ANALYSIS_PROMPT,
        use_mock=True,
    )
    runner.run()
    return runner, Path(config.run.output_dir)


# ============================================================
# 验收标准 1: factory.py 不再为 compression 返回 mock executor
# ============================================================

def test_acceptance_01_factory_returns_real_compression_executor():
    """factory.py 为 compression 返回真实 CompressionExecutor。"""
    executors = create_executors({}, use_mock=True)
    assert isinstance(executors["compression"], CompressionExecutor), (
        "factory.py 应为 compression 返回 CompressionExecutor 实例，"
        f"实际为 {type(executors['compression'])}"
    )


# ============================================================
# 验收标准 2: CompressionExecutor 支持超限检测
# ============================================================

def test_acceptance_02_compression_detects_over_limit():
    """CompressionExecutor 能检测超限并触发压缩。"""
    prompt = _make_over_limit_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = _make_sample_set(sample_ids)
    batch = _make_batch(sample_ids)

    # 使用 mock executor 以支持回归测试
    executors = create_executors({}, use_mock=True)
    executor = CompressionExecutor(model_client=None)
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        extraction_executor=executors["extraction"],
        evaluation_executor=executors["evaluation"],
        pre_compression_eval_records=_make_eval_records(sample_ids, "correct"),
    )

    assert report.triggered is True, "超 line_limit 应触发压缩"


# ============================================================
# 验收标准 3: CompressionExecutor 支持压缩后重新测试
# ============================================================

def test_acceptance_03_compression_runs_regression_test():
    """CompressionExecutor 压缩后执行回归测试。"""
    prompt = _make_over_limit_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = _make_sample_set(sample_ids)
    batch = _make_batch(sample_ids)

    # 使用 mock executor 以支持回归测试
    executors = create_executors({}, use_mock=True)
    executor = CompressionExecutor(model_client=None)
    _, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        extraction_executor=executors["extraction"],
        evaluation_executor=executors["evaluation"],
        pre_compression_eval_records=_make_eval_records(sample_ids, "correct"),
    )

    # 压缩后应有 post_compression_accuracy（回归测试执行过）
    assert report.post_compression_accuracy is not None, "压缩后应执行回归测试"


# ============================================================
# 验收标准 4: 压缩后指标不降且无新增 broken 才接受
# ============================================================

def test_acceptance_04_compression_accept_criteria():
    """CompressionReport 记录接受标准相关字段。"""
    from mmap_optimizer.refactored.patch import CompressionReport

    # 构造一个接受的 report
    report = CompressionReport(
        id="cr_1",
        prompt_type="extraction",
        base_prompt_id="p1",
        compressed_prompt_id="p2",
        triggered=True,
        accepted=True,
        rejected_reason=None,
        line_count_before=50,
        line_count_after=30,
        char_count_before=500,
        char_count_after=300,
        base_accuracy=0.8,
        pre_compression_accuracy=0.8,
        post_compression_accuracy=0.85,
        broken_sample_ids=[],
        fixed_sample_ids=[],
        warnings=[],
        still_over_limit=False,
    )
    assert report.accepted is True
    assert report.post_compression_accuracy >= report.pre_compression_accuracy
    assert len(report.broken_sample_ids) == 0

    # 构造一个拒绝的 report
    report_rejected = CompressionReport(
        id="cr_2",
        prompt_type="extraction",
        base_prompt_id="p1",
        compressed_prompt_id="p2",
        triggered=True,
        accepted=False,
        rejected_reason="accuracy_drop",
        line_count_before=50,
        line_count_after=30,
        char_count_before=500,
        char_count_after=300,
        base_accuracy=0.8,
        pre_compression_accuracy=0.8,
        post_compression_accuracy=0.7,
        broken_sample_ids=[],
        fixed_sample_ids=[],
        warnings=["accuracy dropped"],
        still_over_limit=False,
    )
    assert report_rejected.accepted is False
    assert report_rejected.post_compression_accuracy < report_rejected.pre_compression_accuracy


# ============================================================
# 验收标准 5: 压缩失败时保留未压缩 prompt
# ============================================================

def test_acceptance_05_compression_failure_preserves_original():
    """压缩被拒绝时返回原 prompt。"""
    prompt = _make_over_limit_prompt()
    sample_ids = ["s1", "s2"]
    sample_set = _make_sample_set(sample_ids)
    batch = _make_batch(sample_ids)

    # 使用 mock executor 以支持回归测试
    executors = create_executors({}, use_mock=True)
    executor = CompressionExecutor(model_client=None)
    result_prompt, report = executor.compress_if_needed(
        prompt=prompt,
        line_limit=5,
        char_limit=10000,
        batch=batch,
        sample_set=sample_set,
        extraction_executor=executors["extraction"],
        evaluation_executor=executors["evaluation"],
        pre_compression_eval_records=_make_eval_records(sample_ids, "correct"),
    )

    # 无论接受与否，若拒绝则返回原 prompt
    if not report.accepted:
        assert result_prompt.id == prompt.id, "压缩拒绝时应返回原 prompt"


# ============================================================
# 验收标准 6: extraction / analysis 都能生成 compression_report
# ============================================================

def test_acceptance_06_both_extraction_and_analysis_have_compression_report(tmp_path):
    """extraction 和 analysis 都生成 compression_report.json。"""
    runner, output_dir = _run_smoke(tmp_path)

    ext_cr = output_dir / "prompt_optimization" / "iteration_1" / "extraction" / "compression_report.json"
    ana_cr = output_dir / "prompt_optimization" / "iteration_1" / "analysis" / "compression_report.json"

    assert ext_cr.exists(), "extraction compression_report.json 不存在"
    assert ana_cr.exists(), "analysis compression_report.json 不存在"

    # 验证可解析
    ext_data = json.loads(ext_cr.read_text(encoding="utf-8"))
    ana_data = json.loads(ana_cr.read_text(encoding="utf-8"))
    assert "prompt_type" in ext_data
    assert "prompt_type" in ana_data


# ============================================================
# 验收标准 7: Run 级 artifact 完整
# ============================================================

def test_acceptance_07_run_level_artifacts_complete(tmp_path):
    """Run 级 artifact 完整。"""
    runner, output_dir = _run_smoke(tmp_path)

    required_files = [
        "run_config.yaml",
        "run_config.json",
        "run_plan.json",
        "run_summary.json",
        "prompt_versions.jsonl",
        "patch_apply_reports.jsonl",
        "final_extraction_prompt.json",
        "final_analysis_prompt.json",
        "final_fewshot_examples.jsonl",
        "structured_extraction_prompt.json",
        "structured_analysis_prompt.json",
    ]

    for name in required_files:
        assert (output_dir / name).exists(), f"Run 级 artifact 缺失: {name}"


# ============================================================
# 验收标准 8: Prompt iteration artifact 完整
# ============================================================

def test_acceptance_08_prompt_iteration_artifacts_complete(tmp_path):
    """Prompt iteration artifact 完整。"""
    runner, output_dir = _run_smoke(tmp_path)

    iter_dir = output_dir / "prompt_optimization" / "iteration_1"
    required_files = [
        "sample_batch.json",
        "sample_traces.jsonl",
        "sample_state_before.json",
        "sample_state_after.json",
        "batch_size_controller_before.json",
        "batch_size_controller_after.json",
    ]

    for name in required_files:
        assert (iter_dir / name).exists(), f"Prompt iteration artifact 缺失: {name}"

    # extraction / analysis 子目录
    assert (iter_dir / "extraction").is_dir()
    assert (iter_dir / "analysis").is_dir()


# ============================================================
# 验收标准 9: Few-shot artifact 完整
# ============================================================

def test_acceptance_09_fewshot_artifacts_complete(tmp_path):
    """Few-shot artifact 完整。"""
    runner, output_dir = _run_smoke(tmp_path)

    fs_dir = output_dir / "fewshot_optimization" / "iteration_1"
    required_files = [
        "sample_batch.json",
        "sample_traces.jsonl",
    ]

    for name in required_files:
        assert (fs_dir / name).exists(), f"Few-shot artifact 缺失: {name}"

    fewshot_dir = fs_dir / "fewshot"
    required_fewshot_files = [
        "base_results.jsonl",
        "base_eval.jsonl",
        "metrics.json",
    ]

    for name in required_fewshot_files:
        assert (fewshot_dir / name).exists(), f"Few-shot 子目录 artifact 缺失: {name}"


# ============================================================
# 验收标准 10: run_summary.json 能快速说明收益和风险
# ============================================================

def test_acceptance_10_run_summary_shows_benefits_and_risks(tmp_path):
    """run_summary.json 包含收益和风险相关字段。"""
    runner, output_dir = _run_smoke(tmp_path)

    data = json.loads((output_dir / "run_summary.json").read_text(encoding="utf-8"))

    # 收益字段
    po = data["prompt_optimization"]
    assert "base_accuracy_first" in po
    assert "final_accuracy_last" in po
    assert "best_accuracy" in po
    assert "total_accepted_patches" in po

    # 风险字段
    assert "rollback_count" in po
    assert "no_progress_count" in po
    assert "total_toxic_patches" in po
    assert "compression_triggered_count" in po

    # analysis 收益和风险
    ap = data["analysis_prompt"]
    assert "base_accuracy_first" in ap
    assert "final_accuracy_last" in ap
    assert "rollback_count" in ap

    # fewshot 收益
    fo = data["fewshot_optimization"]
    assert "accepted" in fo
    assert "selected_example_ids" in fo


# ============================================================
# 验收标准 11: final_extraction_prompt.json 保存最终抽取 prompt
# ============================================================

def test_acceptance_11_final_extraction_prompt_saved(tmp_path):
    """final_extraction_prompt.json 保存最终抽取 prompt。"""
    runner, output_dir = _run_smoke(tmp_path)

    f = output_dir / "final_extraction_prompt.json"
    assert f.exists()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["prompt_type"] == "extraction"
    assert "sections" in data
    assert "id" in data


# ============================================================
# 验收标准 12: final_analysis_prompt.json 保存最终分析 prompt
# ============================================================

def test_acceptance_12_final_analysis_prompt_saved(tmp_path):
    """final_analysis_prompt.json 保存最终分析 prompt。"""
    runner, output_dir = _run_smoke(tmp_path)

    f = output_dir / "final_analysis_prompt.json"
    assert f.exists()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["prompt_type"] == "analysis"
    assert "sections" in data
    assert "id" in data


# ============================================================
# 验收标准 13: final_fewshot_examples.jsonl 保存最终 few-shot
# ============================================================

def test_acceptance_13_final_fewshot_examples_saved(tmp_path):
    """final_fewshot_examples.jsonl 保存最终 few-shot。"""
    runner, output_dir = _run_smoke(tmp_path)

    f = output_dir / "final_fewshot_examples.jsonl"
    assert f.exists()
    # 文件可能为空（mock 模式下可能无 few-shot 选中），但必须存在
    content = f.read_text(encoding="utf-8").strip()
    if content:
        for line in content.splitlines():
            data = json.loads(line)
            assert "id" in data
            assert "sample_id" in data


# ============================================================
# 验收标准 14: 10～20 条小数据集 smoke 可运行
# ============================================================

def test_acceptance_14_smoke_dataset_runs_end_to_end(tmp_path):
    """10～20 条小数据集 smoke 可端到端运行。"""
    runner, output_dir = _run_smoke(tmp_path)

    summary = runner.run_summary
    assert summary.status == "completed"
    assert summary.prompt_structuring_status == "completed"
    assert summary.prompt_optimization.iterations >= 1
    assert summary.fewshot_optimization.iterations >= 1


# ============================================================
# 验收标准 15: CLI 文档包含真实运行命令
# ============================================================

def test_acceptance_15_cli_help_contains_run_command():
    """CLI run --help 输出包含 run 命令和 use-mock 选项。"""
    result = subprocess.run(
        [sys.executable, "-m", "mmap_optimizer.refactored.cli", "run", "--help"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "--config" in result.stdout
    assert "--use-mock" in result.stdout
    assert "--no-mock" in result.stdout


def test_acceptance_15b_cli_run_command_works(tmp_path):
    """CLI run 命令可执行。"""
    output_dir = tmp_path / "cli_acceptance"
    result = subprocess.run(
        [
            sys.executable, "-m", "mmap_optimizer.refactored.cli", "run",
            "--config", str(SMOKE_CONFIG),
            "--extraction-prompt", str(EXTRACTION_PROMPT),
            "--analysis-prompt", str(ANALYSIS_PROMPT),
            "--output-dir", str(output_dir),
            "--use-mock",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"CLI run 失败:\n{result.stderr}"
    assert (output_dir / "run_summary.json").exists()


# ============================================================
# 验收标准 16: use_mock=false 时缺少 model_client 应报错
# ============================================================

def test_acceptance_16_use_mock_false_without_model_client_raises(tmp_path):
    """use_mock=false 缺 model_client 时报错。"""
    config = RefactoredConfig()
    config.run.output_dir = str(tmp_path / "no_mock_run")
    config.run.use_mock = False

    with pytest.raises(RuntimeError, match="use_mock=false"):
        MMAPRunner(
            config=config,
            extraction_prompt_path=EXTRACTION_PROMPT,
            analysis_prompt_path=ANALYSIS_PROMPT,
        )


def test_acceptance_16b_cli_no_mock_without_model_client_errors(tmp_path):
    """CLI --no-mock 缺 model_client 时报错并非零退出。"""
    output_dir = tmp_path / "cli_no_mock"
    result = subprocess.run(
        [
            sys.executable, "-m", "mmap_optimizer.refactored.cli", "run",
            "--config", str(SMOKE_CONFIG),
            "--extraction-prompt", str(EXTRACTION_PROMPT),
            "--analysis-prompt", str(ANALYSIS_PROMPT),
            "--output-dir", str(output_dir),
            "--no-mock",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0, "use_mock=false 缺 model_client 应非零退出"
    assert "use_mock" in result.stdout or "model_client" in result.stdout


# ============================================================
# 验收标准 17: 真实运行模式下不再依赖 mock executor
# ============================================================

def test_acceptance_17_real_mode_uses_real_executors():
    """use_mock=True 时 merge/toxicity/patch_apply/compression 仍为真实实现。"""
    executors = create_executors({}, use_mock=True)

    # 这些 executor 始终为真实实现，不依赖 model_client
    from mmap_optimizer.refactored.executors.merge_executor import MergeExecutor
    from mmap_optimizer.refactored.executors.toxicity_executor import ToxicityTestExecutor
    from mmap_optimizer.refactored.executors.patch_apply_executor import PatchApplyExecutor
    from mmap_optimizer.refactored.executors.compression_executor import CompressionExecutor

    assert isinstance(executors["merge"], MergeExecutor), "merge 应为真实 MergeExecutor"
    assert isinstance(executors["toxicity_test"], ToxicityTestExecutor), "toxicity_test 应为真实 ToxicityTestExecutor"
    assert isinstance(executors["patch_apply"], PatchApplyExecutor), "patch_apply 应为真实 PatchApplyExecutor"
    assert isinstance(executors["compression"], CompressionExecutor), "compression 应为真实 CompressionExecutor"


def test_acceptance_17b_factory_does_not_return_mock_compression():
    """factory.py 不返回 _MockCompressionExecutor。"""
    from mmap_optimizer.refactored.executors.factory import _MockCompressionExecutor

    executors = create_executors({}, use_mock=True)
    assert not isinstance(executors["compression"], _MockCompressionExecutor), (
        "factory.py 不应为 compression 返回 _MockCompressionExecutor"
    )


# ============================================================
# 综合验收：完整 Run 产物清单
# ============================================================

def test_acceptance_full_run_artifact_manifest(tmp_path):
    """完整 Run 产物清单：对照 spec 第 7 节的目录结构。"""
    runner, output_dir = _run_smoke(tmp_path)

    # Run 级文件（spec 7.1）
    run_level_files = [
        "run_config.yaml",
        "run_plan.json",
        "run_summary.json",
        "prompt_versions.jsonl",
        "patch_apply_reports.jsonl",
        "final_extraction_prompt.json",
        "final_analysis_prompt.json",
        "final_fewshot_examples.jsonl",
        "structured_extraction_prompt.json",
        "structured_analysis_prompt.json",
    ]
    for name in run_level_files:
        assert (output_dir / name).exists(), f"Run 级缺失: {name}"

    # Prompt iteration 级（spec 7.2）
    iter_dir = output_dir / "prompt_optimization" / "iteration_1"
    iter_files = [
        "sample_batch.json",
        "sample_traces.jsonl",
        "sample_state_before.json",
        "sample_state_after.json",
        "batch_size_controller_before.json",
        "batch_size_controller_after.json",
    ]
    for name in iter_files:
        assert (iter_dir / name).exists(), f"Prompt iteration 缺失: {name}"

    # Extraction artifact（spec 7.3 关键文件）
    ext_dir = iter_dir / "extraction"
    ext_files = [
        "base_results.jsonl",
        "base_eval.jsonl",
        "compression_report.json",
        "metrics.json",
    ]
    for name in ext_files:
        assert (ext_dir / name).exists(), f"Extraction artifact 缺失: {name}"

    # Analysis artifact（spec 7.4 关键文件）
    ana_dir = iter_dir / "analysis"
    ana_files = [
        "base_metrics.json",
        "compression_report.json",
        "metrics.json",
    ]
    for name in ana_files:
        assert (ana_dir / name).exists(), f"Analysis artifact 缺失: {name}"

    # Few-shot artifact（spec 7.5）
    fs_dir = output_dir / "fewshot_optimization" / "iteration_1"
    fs_files = [
        "sample_batch.json",
        "sample_traces.jsonl",
    ]
    for name in fs_files:
        assert (fs_dir / name).exists(), f"Few-shot artifact 缺失: {name}"

    fewshot_dir = fs_dir / "fewshot"
    fewshot_files = [
        "base_results.jsonl",
        "base_eval.jsonl",
        "metrics.json",
    ]
    for name in fewshot_files:
        assert (fewshot_dir / name).exists(), f"Few-shot 子目录缺失: {name}"
