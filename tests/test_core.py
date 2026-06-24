"""重构版 MMAP 模块测试。

验证所有模块可以正确导入和基本功能。
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_imports():
    """测试所有模块导入。"""
    print("测试模块导入...")

    try:
        from mmap_optimizer import (
            # Sample
            SampleAsset,
            SampleSpec,
            SampleState,
            SampleTrace,
            SampleSet,
            SampleBatch,
            # Dataset
            DatasetLoader,
            load_sample_specs,
            create_sample_set,
            # Sampler
            SamplerConfig,
            BaseSampler,
            RandomSampler,
            DifficultySampler,
            FrequencySampler,
            DifficultyFrequencySampler,
            create_sampler,
            # Batch Size Controller
            BatchSizeControllerConfig,
            BatchSizeControllerState,
            BatchSizeController,
            # Structured Prompt
            PromptSection,
            StructuredPrompt,
            # Prompt Structuring Phase
            PromptStructuringConfig,
            MarkdownParser,
            PromptStructuringPhase,
            # Patch
            ExtractionPatch,
            AnalysisPatch,
            PatchMergeReport,
            ToxicityReport,
            # Extraction Prompt Optimization Stage
            ExtractionResult,
            AnalysisResult,
            EvalRecord,
            ExtractionMetrics,
            ExtractionPromptOptimizationStage,
            # Analysis Prompt Optimization Stage
            ReflectionResult,
            AnalysisMetrics,
            AnalysisPromptOptimizationStage,
            # Prompt Optimization Phase
            PromptOptimizationConfig,
            PromptOptimizationIterationResult,
            PromptOptimizationPhase,
            # Few-shot Optimization Phase
            FewshotExample,
            FewshotConfig,
            FewshotMetrics,
            FewshotOptimizationIterationResult,
            FewshotOptimizationPhase,
            # Config
            RunConfig,
            DatasetConfig,
            RefactoredConfig,
            load_config,
            # Runner
            RunPlanStep,
            RunPlan,
            RunSummary,
            MMAPRunner,
        )
        print("✓ 所有模块导入成功")
        return True
    except Exception as e:
        print(f"✗ 导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_sample_models():
    """测试 Sample 模型。"""
    print("\n测试 Sample 模型...")

    from mmap_optimizer import SampleSpec, SampleState, SampleTrace, SampleSet

    # 创建 SampleSpec
    spec = SampleSpec(
        id="sample_001",
        input={"text": "test input"},
        ground_truth={"answer": "test answer"},
    )
    print(f"✓ SampleSpec 创建成功: {spec.id}")

    # 创建 SampleState
    state = SampleState(sample_id="sample_001")
    state.update_selection(selected=True, iteration=1)
    state.update_error(has_error=False)
    print(f"✓ SampleState 创建成功: selected_count={state.selected_count}, difficulty_score={state.difficulty_score}")

    # 创建 SampleSet
    sample_set = SampleSet()
    sample_set.add_spec(spec)
    print(f"✓ SampleSet 创建成功: {len(sample_set.specs)} specs")

    return True


def test_sampler():
    """测试抽样策略。"""
    print("\n测试抽样策略...")

    from mmap_optimizer import (
        SamplerConfig,
        create_sampler,
        RandomSampler,
        DifficultySampler,
        FrequencySampler,
        DifficultyFrequencySampler,
        SampleSet,
        SampleSpec,
    )

    # 创建样本集合
    sample_set = SampleSet()
    for i in range(10):
        spec = SampleSpec(
            id=f"sample_{i}",
            input={"text": f"input {i}"},
            ground_truth={"answer": f"answer {i}"},
        )
        sample_set.add_spec(spec)

    # 测试各种抽样器
    for sampler_type in ["random", "difficulty", "frequency", "difficulty_frequency"]:
        config = SamplerConfig(type=sampler_type)
        sampler = create_sampler(config)
        batch = sampler.sample(sample_set, batch_size=5, iteration=1, seed=42)
        print(f"✓ {sampler_type} sampler: {len(batch.sample_ids)} samples selected")

    return True


def test_batch_size_controller():
    """测试 Batch Size Controller。"""
    print("\n测试 Batch Size Controller...")

    from mmap_optimizer import BatchSizeController, BatchSizeControllerConfig

    config = BatchSizeControllerConfig(
        initial_batch_size=16,
        min_batch_size=8,
        max_batch_size=99,
    )
    controller = BatchSizeController(config)

    print(f"✓ 初始 batch size: {controller.get_current_batch_size()}")

    # 测试指标上升
    next_size = controller.update(base_accuracy=0.5, final_accuracy=0.7)
    print(f"✓ 指标上升后 batch size: {next_size}")

    # 测试指标下降
    next_size = controller.update(base_accuracy=0.7, final_accuracy=0.6)
    print(f"✓ 指标下降后 batch size: {next_size}")

    return True


def test_structured_prompt():
    """测试结构化 Prompt。"""
    print("\n测试结构化 Prompt...")

    from mmap_optimizer import PromptSection, StructuredPrompt

    section = PromptSection(
        id="section_1",
        title="Introduction",
        level=1,
        content="This is the introduction section.",
        bullets=["Point 1", "Point 2"],
    )
    print(f"✓ PromptSection 创建成功: {section.title}")

    prompt = StructuredPrompt(
        id="test_prompt",
        prompt_type="extraction",
        sections=[section],
        raw_markdown="# Introduction\n\nThis is the introduction section.\n\n- Point 1\n- Point 2",
    )
    print(f"✓ StructuredPrompt 创建成功: {prompt.id}")

    markdown = prompt.to_markdown()
    print(f"✓ Markdown 转换成功")

    return True


def test_config():
    """测试配置加载。"""
    print("\n测试配置...")

    from mmap_optimizer import RefactoredConfig, RunConfig, DatasetConfig

    config = RefactoredConfig()
    print(f"✓ RefactoredConfig 创建成功")
    print(f"  - Prompt Optimization rounds: {config.prompt_optimization.rounds}")
    print(f"  - Few-shot Optimization rounds: {config.fewshot_optimization.rounds}")

    config_dict = config.to_dict()
    print(f"✓ 配置转换为字典成功")

    return True


def test_run_plan():
    """测试 Run Plan。"""
    print("\n测试 Run Plan...")

    from mmap_optimizer import RunPlan, RunPlanStep

    steps = [
        RunPlanStep(id="prompt_structuring", phase="prompt_structuring"),
        RunPlanStep(id="prompt_iter_001", phase="prompt_optimization", iteration=1),
        RunPlanStep(id="fewshot_iter_001", phase="fewshot_optimization", iteration=1),
    ]

    run_plan = RunPlan(id="test_plan", steps=steps)
    print(f"✓ RunPlan 创建成功: {len(run_plan.steps)} steps")

    current = run_plan.get_current_step()
    print(f"✓ 当前步骤: {current.id}")

    run_plan.advance()
    current = run_plan.get_current_step()
    print(f"✓ 推进后当前步骤: {current.id}")

    return True


def test_analysis_executor():
    """测试 AnalysisExecutor 真实实现（盲评模式）。"""
    print("\n测试 AnalysisExecutor...")

    import json as _json

    from mmap_optimizer.model.client import MockModelClient
    from mmap_optimizer.executors.analysis_executor import AnalysisExecutor
    from mmap_optimizer.stages.extraction_prompt_optimization import (
        AnalysisResult,
        ExtractionResult,
    )
    from mmap_optimizer.data.sample import SampleSet, SampleSpec
    from mmap_optimizer.prompt.structured_prompt import (
        PromptSection,
        StructuredPrompt,
    )

    analysis_prompt = StructuredPrompt(
        id="a1",
        prompt_type="analysis",
        sections=[PromptSection(id="s1", title="Analysis", level=1, content="Analyze extraction")],
        raw_markdown="# Analysis",
    )
    extraction_prompt = StructuredPrompt(
        id="e1",
        prompt_type="extraction",
        sections=[PromptSection(id="s1", title="Extract", level=1, content="Extract info")],
        raw_markdown="# Extract",
    )

    def _spec(sid, gt):
        return SampleSpec(id=sid, input={"text": "hello"}, ground_truth=gt)

    # 正常 analysis 输出能正确解析 + analysis_correct 判定正确（extraction 正确，分析也判正确）
    executor_ok = AnalysisExecutor(MockModelClient(_json.dumps({
        "judgement": {"is_correct": True},
        "error_reason": None,
        "confirmed_facts": ["fact1"],
        "hypothesized_error_causes": [],
    })))
    spec_ok = _spec("s1", {"result": "OK"})
    er_ok = ExtractionResult(
        sample_id="s1", raw_output='{"result":"OK"}', parsed_output={"result": "OK"}, status="correct"
    )
    r_ok = executor_ok.execute(analysis_prompt, extraction_prompt, er_ok, spec_ok)
    assert r_ok.analysis_correct is True, "extraction 正确且分析判正确时 analysis_correct 应为 True"
    assert r_ok.judgement["judgement"]["is_correct"] is True
    assert isinstance(r_ok.confirmed_facts, list)
    assert isinstance(r_ok.hypothesized_error_causes, list)
    print(f"✓ 正确样本分析: analysis_correct={r_ok.analysis_correct}")

    # 错误样本（extraction 错误，分析正确识别）
    executor_wrong = AnalysisExecutor(
        MockModelClient(
            _json.dumps(
                {
                    "judgement": {"is_correct": False},
                    "error_reason": "wrong label",
                    "confirmed_facts": ["image shows OK stamp"],
                    "hypothesized_error_causes": ["prompt missed OK stamp rule"],
                }
            )
        )
    )
    spec_wrong = _spec("s2", {"result": "OK"})
    er_wrong = ExtractionResult(
        sample_id="s2", raw_output='{"result":"NG"}', parsed_output={"result": "NG"}, status="wrong"
    )
    r_wrong = executor_wrong.execute(analysis_prompt, extraction_prompt, er_wrong, spec_wrong)
    assert r_wrong.analysis_correct is True, "extraction 错误且分析判错误时 analysis_correct 应为 True"
    assert r_wrong.error_reason == "wrong label"
    assert r_wrong.confirmed_facts == ["image shows OK stamp"]
    assert r_wrong.hypothesized_error_causes == ["prompt missed OK stamp rule"]
    print(f"✓ 错误样本分析: error_reason={r_wrong.error_reason}")

    # 分析误判：extraction 错误但分析判正确 -> analysis_correct=False
    executor_misjudge = AnalysisExecutor(MockModelClient(_json.dumps({"judgement": {"is_correct": True}})))
    r_misjudge = executor_misjudge.execute(analysis_prompt, extraction_prompt, er_wrong, spec_wrong)
    assert r_misjudge.analysis_correct is False, "分析误判时 analysis_correct 应为 False"
    print(f"✓ 分析误判: analysis_correct={r_misjudge.analysis_correct}")

    # 盲评模式：AnalysisResult 不包含 patch_suggestion（patch 由 PatchGenerationExecutor 生成）
    assert not hasattr(r_ok, "patch_suggestion") or r_ok.__dict__.get("patch_suggestion") is None
    print("✓ 盲评模式: AnalysisResult 不含 patch_suggestion")

    # reflect 方法能产出 ReflectionResult
    executor_reflect = AnalysisExecutor(
        MockModelClient(
            _json.dumps(
                {
                    "error_reason": "missed signal",
                    "patch_suggestion": {"target_section": "sec2", "operation": "append", "content": "add rule"},
                    "notes": ["note1"],
                }
            )
        )
    )
    ar_reflect = AnalysisResult(
        sample_id="s2", judgement={"is_correct": True}, analysis_correct=False, error_reason="misjudged"
    )
    rr = executor_reflect.reflect(analysis_prompt, er_wrong, ar_reflect, spec_wrong)
    assert rr.sample_id == "s2"
    assert rr.reflection_success is True
    assert rr.patch_suggestion["content"] == "add rule"
    assert rr.notes == ["note1"]
    print(f"✓ reflect 产出 ReflectionResult: success={rr.reflection_success}")

    # execute_batch 分析所有样本（不只错误样本）
    executor_batch = AnalysisExecutor(MockModelClient(_json.dumps({"judgement": {"is_correct": True}})))
    sample_set = SampleSet()
    sample_set.add_spec(spec_ok)
    sample_set.add_spec(spec_wrong)
    batch_results = executor_batch.execute_batch(
        analysis_prompt, extraction_prompt, [er_ok, er_wrong], sample_set
    )
    assert len(batch_results) == 2, "execute_batch 应分析所有样本"
    print(f"✓ execute_batch 分析 {len(batch_results)} 个样本")

    return True


def main():
    """运行所有测试。"""
    print("=" * 60)
    print("MMAP 重构版模块测试")
    print("=" * 60)

    tests = [
        test_imports,
        test_sample_models,
        test_sampler,
        test_batch_size_controller,
        test_structured_prompt,
        test_config,
        test_run_plan,
        test_analysis_executor,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"✗ 测试失败: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"测试结果: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)