"""PR4 Task 32: Run Summary 扩展与 Mock 边界收敛单元测试。

覆盖：
1. RunSummary 嵌套对象字段完整；
2. RunSummary 向后兼容属性；
3. RunSummary.to_dict() 输出 v1.4 结构；
4. create_executors(use_mock=True) 返回 mock executor；
5. create_executors(use_mock=False) 缺 model_client 时报错；
6. create_executors(use_mock=None) 自动回退 mock；
7. MMAPRunner(use_mock=False) 缺 model_client 时报错；
8. MMAPRunner(use_mock=True) 正常初始化；
9. RunConfig.use_mock 字段读写；
10. 端到端 run 生成 run_summary.json 包含 v1.4 字段。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmap_optimizer.config import RefactoredConfig, RunConfig, load_config
from mmap_optimizer.executors.factory import create_executors
from mmap_optimizer.runner import (
    AnalysisPromptSummary,
    FewshotOptimizationSummary,
    MMAPRunner,
    PromptOptimizationSummary,
    RunSummary,
)


# ============================================================
# RunSummary 嵌套对象测试
# ============================================================

def test_run_summary_nested_objects_default():
    """RunSummary 默认包含嵌套对象。"""
    summary = RunSummary(id="run_001")
    assert isinstance(summary.prompt_optimization, PromptOptimizationSummary)
    assert isinstance(summary.analysis_prompt, AnalysisPromptSummary)
    assert isinstance(summary.fewshot_optimization, FewshotOptimizationSummary)
    assert summary.prompt_optimization.iterations == 0
    assert summary.analysis_prompt.total_accepted_patches == 0
    assert summary.fewshot_optimization.accepted is False


def test_run_summary_time_fields():
    """RunSummary 包含时间字段。"""
    summary = RunSummary(id="run_001")
    assert summary.start_time is None
    assert summary.end_time is None
    assert summary.duration_seconds is None
    assert summary.prompt_structuring_status == "pending"

    summary.start_time = "2026-06-23T10:00:00+00:00"
    summary.end_time = "2026-06-23T10:05:00+00:00"
    summary.duration_seconds = 300.0
    summary.prompt_structuring_status = "completed"

    assert summary.start_time == "2026-06-23T10:00:00+00:00"
    assert summary.duration_seconds == 300.0
    assert summary.prompt_structuring_status == "completed"


def test_run_summary_backward_compatible_properties():
    """RunSummary 向后兼容属性从嵌套对象派生。"""
    summary = RunSummary(id="run_001")
    summary.prompt_structuring_status = "completed"
    summary.prompt_optimization.iterations = 3
    summary.prompt_optimization.total_accepted_patches = 5
    summary.prompt_optimization.base_accuracy_first = 0.6
    summary.prompt_optimization.final_accuracy_last = 0.8
    summary.analysis_prompt.total_accepted_patches = 2
    summary.analysis_prompt.base_accuracy_first = 0.5
    summary.analysis_prompt.final_accuracy_last = 0.7
    summary.fewshot_optimization.iterations = 1
    summary.fewshot_optimization.base_accuracy_first = 0.8
    summary.fewshot_optimization.final_accuracy_last = 0.85

    # 向后兼容属性
    assert summary.prompt_structuring_completed is True
    assert summary.prompt_optimization_rounds == 3
    assert summary.fewshot_optimization_rounds == 1
    assert summary.total_extraction_accepted_patches == 5
    assert summary.total_analysis_accepted_patches == 2
    assert pytest.approx(summary.extraction_accuracy_delta) == 0.2
    assert pytest.approx(summary.analysis_accuracy_delta) == 0.2
    assert pytest.approx(summary.fewshot_accuracy_delta) == 0.05


def test_run_summary_to_dict_v14_structure():
    """RunSummary.to_dict() 输出 v1.4 结构。"""
    summary = RunSummary(id="run_001")
    summary.status = "completed"
    summary.start_time = "2026-06-23T10:00:00+00:00"
    summary.end_time = "2026-06-23T10:05:00+00:00"
    summary.duration_seconds = 300.0
    summary.prompt_structuring_status = "completed"
    summary.prompt_optimization.iterations = 2
    summary.prompt_optimization.base_accuracy_first = 0.6
    summary.prompt_optimization.final_accuracy_last = 0.8
    summary.prompt_optimization.best_accuracy = 0.85
    summary.prompt_optimization.total_accepted_patches = 3
    summary.prompt_optimization.total_rejected_patches = 1
    summary.prompt_optimization.total_toxic_patches = 0
    summary.prompt_optimization.rollback_count = 0
    summary.prompt_optimization.no_progress_count = 0
    summary.prompt_optimization.compression_triggered_count = 1
    summary.prompt_optimization.compression_accepted_count = 1
    summary.prompt_optimization.batch_size_history = [{"iteration": 1, "batch_size": 10}]
    summary.analysis_prompt.base_accuracy_first = 0.5
    summary.analysis_prompt.final_accuracy_last = 0.7
    summary.analysis_prompt.total_accepted_patches = 2
    summary.fewshot_optimization.iterations = 1
    summary.fewshot_optimization.selected_example_ids = ["ex_001", "ex_002"]
    summary.fewshot_optimization.accepted = True
    summary.final_extraction_prompt_id = "prompt_ext_final"
    summary.final_analysis_prompt_id = "prompt_ana_final"
    summary.final_fewshot_example_count = 2

    d = summary.to_dict()

    # 顶层字段
    assert d["id"] == "run_001"
    assert d["status"] == "completed"
    assert d["start_time"] == "2026-06-23T10:00:00+00:00"
    assert d["end_time"] == "2026-06-23T10:05:00+00:00"
    assert d["duration_seconds"] == 300.0
    assert d["prompt_structuring_status"] == "completed"

    # 嵌套 prompt_optimization
    po = d["prompt_optimization"]
    assert po["iterations"] == 2
    assert po["base_accuracy_first"] == 0.6
    assert po["final_accuracy_last"] == 0.8
    assert po["best_accuracy"] == 0.85
    assert po["total_accepted_patches"] == 3
    assert po["total_rejected_patches"] == 1
    assert po["total_toxic_patches"] == 0
    assert po["rollback_count"] == 0
    assert po["no_progress_count"] == 0
    assert po["compression_triggered_count"] == 1
    assert po["compression_accepted_count"] == 1
    assert po["batch_size_history"] == [{"iteration": 1, "batch_size": 10}]

    # 嵌套 analysis_prompt
    ap = d["analysis_prompt"]
    assert ap["base_accuracy_first"] == 0.5
    assert ap["final_accuracy_last"] == 0.7
    assert ap["total_accepted_patches"] == 2

    # 嵌套 fewshot_optimization
    fo = d["fewshot_optimization"]
    assert fo["iterations"] == 1
    assert fo["selected_example_ids"] == ["ex_001", "ex_002"]
    assert fo["accepted"] is True

    # 顶层最终信息
    assert d["final_extraction_prompt_id"] == "prompt_ext_final"
    assert d["final_analysis_prompt_id"] == "prompt_ana_final"
    assert d["final_fewshot_example_count"] == 2


def test_prompt_optimization_summary_all_fields():
    """PromptOptimizationSummary 所有字段可序列化。"""
    s = PromptOptimizationSummary(
        iterations=3,
        base_accuracy_first=0.5,
        final_accuracy_last=0.8,
        best_accuracy=0.85,
        total_accepted_patches=5,
        total_rejected_patches=2,
        total_toxic_patches=1,
        total_ineffective_patches=1,
        rollback_count=1,
        no_progress_count=0,
        compression_triggered_count=2,
        compression_accepted_count=1,
        batch_size_history=[{"iter": 1}],
    )
    d = s.to_dict()
    assert d["iterations"] == 3
    assert d["total_ineffective_patches"] == 1
    assert d["batch_size_history"] == [{"iter": 1}]


def test_analysis_prompt_summary_all_fields():
    """AnalysisPromptSummary 所有字段可序列化。"""
    s = AnalysisPromptSummary(
        base_accuracy_first=0.5,
        final_accuracy_last=0.7,
        total_accepted_patches=3,
        rollback_count=0,
        no_progress_count=1,
        compression_triggered_count=1,
        compression_accepted_count=0,
    )
    d = s.to_dict()
    assert d["base_accuracy_first"] == 0.5
    assert d["compression_accepted_count"] == 0


def test_fewshot_optimization_summary_all_fields():
    """FewshotOptimizationSummary 所有字段可序列化。"""
    s = FewshotOptimizationSummary(
        iterations=2,
        base_accuracy_first=0.7,
        final_accuracy_last=0.8,
        selected_example_ids=["ex_1", "ex_2"],
        accepted=True,
    )
    d = s.to_dict()
    assert d["iterations"] == 2
    assert d["selected_example_ids"] == ["ex_1", "ex_2"]
    assert d["accepted"] is True


# ============================================================
# Mock 边界收敛测试
# ============================================================

def test_run_config_use_mock_field():
    """RunConfig 包含 use_mock 字段。"""
    rc = RunConfig()
    assert rc.use_mock is None

    rc_true = RunConfig(use_mock=True)
    assert rc_true.use_mock is True

    rc_false = RunConfig(use_mock=False)
    assert rc_false.use_mock is False


def test_config_to_dict_includes_use_mock():
    """RefactoredConfig.to_dict() 包含 use_mock。"""
    config = RefactoredConfig()
    config.run.use_mock = True
    d = config.to_dict()
    assert d["run"]["use_mock"] is True


def test_config_from_dict_reads_use_mock():
    """RefactoredConfig.from_dict() 读取 use_mock。"""
    data = {"run": {"seed": 1, "output_dir": "x", "use_mock": False}}
    config = RefactoredConfig.from_dict(data)
    assert config.run.use_mock is False


def test_create_executors_use_mock_true_returns_mock():
    """use_mock=True 返回 mock executor。"""
    executors = create_executors({}, use_mock=True)
    from mmap_optimizer.executors.factory import (
        _MockExtractionExecutor,
        _MockEvaluationExecutor,
        _MockAnalysisExecutor,
        _MockFewshotExecutor,
    )
    assert isinstance(executors["extraction"], _MockExtractionExecutor)
    assert isinstance(executors["evaluation"], _MockEvaluationExecutor)
    assert isinstance(executors["analysis"], _MockAnalysisExecutor)
    assert isinstance(executors["fewshot"], _MockFewshotExecutor)
    # merge / toxicity / patch_apply 始终为真实实现（不依赖 model_client）
    from mmap_optimizer.executors.merge_executor import MergeExecutor
    from mmap_optimizer.executors.toxicity_executor import ToxicityTestExecutor
    from mmap_optimizer.executors.patch_apply_executor import PatchApplyExecutor
    assert isinstance(executors["merge"], MergeExecutor)
    assert isinstance(executors["toxicity_test"], ToxicityTestExecutor)
    assert isinstance(executors["patch_apply"], PatchApplyExecutor)


def test_create_executors_use_mock_false_without_model_client_raises():
    """use_mock=False 且无 model_client 时报错。"""
    with pytest.raises(RuntimeError, match="use_mock=false"):
        create_executors({}, use_mock=False)


def test_create_executors_use_mock_none_falls_back_to_mock():
    """use_mock=None 无 model_client 时自动回退 mock。"""
    executors = create_executors({}, use_mock=None)
    from mmap_optimizer.executors.factory import _MockExtractionExecutor
    assert isinstance(executors["extraction"], _MockExtractionExecutor)
    assert executors["model_client"] is None


def test_runner_use_mock_false_without_model_client_raises(tmp_path):
    """MMAPRunner(use_mock=False) 缺 model_client 时报错。"""
    config = RefactoredConfig()
    config.run.output_dir = str(tmp_path / "run")
    config.run.use_mock = False

    # 创建临时 prompt 文件
    ext_path = tmp_path / "ext.txt"
    ext_path.write_text("extraction prompt", encoding="utf-8")
    ana_path = tmp_path / "ana.txt"
    ana_path.write_text("analysis prompt", encoding="utf-8")

    with pytest.raises(RuntimeError, match="use_mock=false"):
        MMAPRunner(
            config=config,
            extraction_prompt_path=ext_path,
            analysis_prompt_path=ana_path,
        )


def test_runner_use_mock_true_initializes(tmp_path):
    """MMAPRunner(use_mock=True) 正常初始化。"""
    config = RefactoredConfig()
    config.run.output_dir = str(tmp_path / "run")
    config.run.use_mock = True
    config.prompt_optimization.enabled = False
    config.fewshot_optimization.enabled = False

    ext_path = tmp_path / "ext.txt"
    ext_path.write_text("extraction prompt", encoding="utf-8")
    ana_path = tmp_path / "ana.txt"
    ana_path.write_text("analysis prompt", encoding="utf-8")

    runner = MMAPRunner(
        config=config,
        extraction_prompt_path=ext_path,
        analysis_prompt_path=ana_path,
        use_mock=True,
    )
    assert runner.use_mock is True
    assert runner.executors.get("model_client") is None


# ============================================================
# 端到端 run_summary.json 生成测试
# ============================================================

def test_end_to_end_run_summary_json_contains_v14_fields(tmp_path):
    """端到端 run 后 run_summary.json 包含 v1.4 字段。"""
    # 准备数据集
    samples_path = tmp_path / "samples.jsonl"
    samples = [
        {"id": "s1", "input": {"text": "case1"}, "ground_truth": {"answer": "a"}},
        {"id": "s2", "input": {"text": "case2"}, "ground_truth": {"answer": "b"}},
    ]
    samples_path.write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in samples),
        encoding="utf-8",
    )

    # 准备 prompt 文件
    ext_path = tmp_path / "ext.txt"
    ext_path.write_text("# Extraction Prompt\n\n请抽取以下信息。\n", encoding="utf-8")
    ana_path = tmp_path / "ana.txt"
    ana_path.write_text("# Analysis Prompt\n\n请分析以下结果。\n", encoding="utf-8")

    # 配置
    config = RefactoredConfig()
    config.run.output_dir = str(tmp_path / "run_output")
    config.run.use_mock = True
    config.dataset.path = str(samples_path)
    config.dataset.ground_truth_path = None
    config.prompt_optimization.enabled = True
    config.prompt_optimization.rounds = 1
    config.prompt_optimization.initial_batch_size = 2
    config.prompt_optimization.min_batch_size = 2
    config.prompt_optimization.max_batch_size = 5
    config.fewshot_optimization.enabled = True
    config.fewshot_optimization.rounds = 1
    config.fewshot_optimization.batch_size = 2

    runner = MMAPRunner(
        config=config,
        extraction_prompt_path=ext_path,
        analysis_prompt_path=ana_path,
        use_mock=True,
    )
    summary = runner.run()

    # 校验 RunSummary 对象
    assert summary.status == "completed"
    assert summary.start_time is not None
    assert summary.end_time is not None
    assert summary.duration_seconds is not None
    assert summary.duration_seconds >= 0
    assert summary.prompt_structuring_status == "completed"
    assert summary.prompt_optimization.iterations == 1
    assert summary.fewshot_optimization.iterations == 1

    # 校验 run_summary.json 文件
    summary_file = Path(config.run.output_dir) / "run_summary.json"
    assert summary_file.exists()
    data = json.loads(summary_file.read_text(encoding="utf-8"))

    # v1.4 必需字段
    required_top = {
        "id", "status", "start_time", "end_time", "duration_seconds",
        "prompt_structuring_status", "prompt_optimization", "analysis_prompt",
        "fewshot_optimization", "final_extraction_prompt_id", "final_analysis_prompt_id",
        "final_fewshot_example_count", "notes",
    }
    assert required_top.issubset(data.keys())

    # prompt_optimization 嵌套字段
    po = data["prompt_optimization"]
    required_po = {
        "iterations", "base_accuracy_first", "final_accuracy_last", "best_accuracy",
        "total_accepted_patches", "total_rejected_patches", "total_toxic_patches",
        "total_ineffective_patches", "rollback_count", "no_progress_count",
        "compression_triggered_count", "compression_accepted_count", "batch_size_history",
    }
    assert required_po.issubset(po.keys())

    # analysis_prompt 嵌套字段
    ap = data["analysis_prompt"]
    required_ap = {
        "base_accuracy_first", "final_accuracy_last", "total_accepted_patches",
        "rollback_count", "no_progress_count", "compression_triggered_count",
        "compression_accepted_count",
    }
    assert required_ap.issubset(ap.keys())

    # fewshot_optimization 嵌套字段
    fo = data["fewshot_optimization"]
    required_fo = {
        "iterations", "base_accuracy_first", "final_accuracy_last",
        "selected_example_ids", "accepted",
    }
    assert required_fo.issubset(fo.keys())
