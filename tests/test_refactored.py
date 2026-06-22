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
        from mmap_optimizer.refactored import (
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

    from mmap_optimizer.refactored import SampleSpec, SampleState, SampleTrace, SampleSet

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

    from mmap_optimizer.refactored import (
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

    from mmap_optimizer.refactored import BatchSizeController, BatchSizeControllerConfig

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

    from mmap_optimizer.refactored import PromptSection, StructuredPrompt

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

    from mmap_optimizer.refactored import RefactoredConfig, RunConfig, DatasetConfig

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

    from mmap_optimizer.refactored import RunPlan, RunPlanStep

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