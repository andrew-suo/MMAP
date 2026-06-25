# MMAP Optimizer

Multimodal prompt optimization framework that iteratively improves extraction and analysis prompts through automated patch generation, LLM-based merge, validation, compression, and few-shot optimization.

## Features

- **Three-Phase Workflow** — Prompt Structuring → Prompt Optimization → Few-shot Optimization
- **Structured Prompt** — `StructuredPrompt` with section-level control, mutable/protected flags, and version tracking
- **LLM-Based Patch Generation** — Model-driven patch generation based on analysis results and reflection results
- **Parallel Patch Merge** — LLM-based parallel merge with deterministic guardrail (ADD+DELETE conflict + replace n-gram overlap detection), Section-Aware grouping, and root merge for cross-section consistency
- **Patch Validation & Calibration** — PatchValidator with model-based calibration for fuzzy target_section/old_text alignment
- **Three-Level Text Matching** — Exact match → difflib fuzzy match → LLM semantic match for robust patch application
- **Toxicity Testing** — Individual patch validation to prevent regression
- **Compression** — Line-budget and token-budget dual-threshold compression with behavior-preservation gates
- **Few-Shot Optimization** — Greedy slot optimization with persistent candidate pool
- **Multimodal Support** — OpenAI-compatible adapter for image assets as multimodal message parts
- **Centralized Prompt Management** — All LLM prompts stored in `prompts/` directory with CLI/YAML configuration

## Quick Start

```bash
# Smoke run with mock model
python -m mmap_optimizer.core.cli run-smoke \
  --data-dir data \
  --output-dir runs/smoke \
  --batch-size 2 \
  --rounds 2

# Configurable run with real model
python -m mmap_optimizer.core.cli run --config configs/optimizer.yaml

# Validate configuration
python -m mmap_optimizer.core.cli validate --config configs/optimizer.yaml
```

## Architecture

```
mmap_optimizer/
├── core/               # 核心运行器和配置
│   ├── runner.py       # MMAPRunner - 三阶段工作流编排
│   ├── config.py       # OptimizerConfig + PromptsConfig
│   └── cli.py          # CLI 命令行接口
├── phases/             # 三个优化阶段
│   ├── prompt_structuring.py    # Phase 1: Prompt 结构化
│   ├── prompt_optimization.py   # Phase 2: Prompt 优化
│   └── fewshot_optimization.py  # Phase 3: Few-shot 优化
├── stages/             # 阶段内步骤实现
│   ├── extraction_prompt_optimization.py  # 9 步提取提示优化
│   ├── analysis_prompt_optimization.py    # 8 步分析提示优化
│   └── batch_size_controller.py           # 自适应批大小控制
├── executors/          # 执行器
│   ├── extraction_executor.py       # 多模态信息抽取
│   ├── analysis_executor.py         # 盲评分析 + 反思
│   ├── patch_generation_executor.py # LLM 驱动的 patch 生成
│   ├── patch_validator.py           # Patch 校验 + 模型校准
│   ├── patch_apply_executor.py      # Patch 应用 + 三级降级匹配
│   ├── merge_executor.py            # ParallelPatchMerger 包装
│   ├── toxicity_executor.py         # 测毒验证
│   ├── compression_executor.py      # Prompt 压缩
│   └── factory.py                   # 执行器工厂
├── patch/              # Patch 核心模块
│   ├── types.py        # ExtractionPatch, AnalysisPatch, PatchMergeReport
│   ├── tree_reduce.py  # ParallelPatchMerger (LLM 并行合并)
│   ├── conflict.py     # 确定性前筛 (ADD+DELETE + replace 重叠)
│   ├── clusterer.py    # Section-Aware 分组
│   ├── deduplicate.py  # 文本归一化
│   └── text_matcher.py # 三级降级文本匹配
├── prompt/             # Prompt 管理
│   ├── structured_prompt.py  # StructuredPrompt + PromptSection
│   ├── prompt_manager.py     # Prompt 统一管理
│   ├── output_repair.py      # 模型输出修复
│   └── prompt_structuring.py # Prompt 结构化解析
├── data/               # 数据模块
│   ├── sample.py       # SampleSet, SampleSpec, SampleState
│   └── sampler.py      # 抽样策略 (difficulty_frequency 等)
└── model/              # 模型客户端
    └── client.py       # ModelClient (OpenAI-compatible)

prompts/                # 所有 LLM 提示词
├── extraction.txt              # 抽取系统提示词
├── analysis.txt                # 分析系统提示词 (盲评)
├── analysis_reflection.txt     # 分析反思提示词
├── patch_generation.txt        # Patch 生成提示词
├── patch_calibration.txt       # Patch 校准提示词
├── patch_merge.txt             # Patch 合并提示词
├── patch_root_merge.txt        # Root Merge 提示词
├── patch_text_match.txt        # 文本匹配提示词
├── prompt_standardization.txt  # Prompt 标准化提示词
└── output_repair.txt           # 输出修复提示词
```

## Core Concepts

### Three-Phase Workflow

```
Phase 1: Prompt Structuring
  └─ Markdown → StructuredPrompt (7-section standardization)

Phase 2: Prompt Optimization (N iterations)
  ├─ Extraction Prompt Optimization (9 steps)
  │   └─ Extract → Evaluate → Analyze → Generate Patches → Merge → Apply → Toxicity → Compress → Result
  └─ Analysis Prompt Optimization (8 steps)
      └─ Analyze → Reflect → Generate Patches → Merge → Apply → Toxicity → Compress → Result

Phase 3: Few-shot Optimization (N iterations)
  └─ Select candidates → Generate examples → Evaluate → Promote
```

### Patch Lifecycle

```
AnalysisResult / ReflectionResult
    ↓
PatchGenerationExecutor (LLM 生成 patch)
    ↓
PatchValidator (校验 + 模型校准)
    ↓
MergeExecutor → ParallelPatchMerger (LLM 并行合并)
  ├─ deterministic_guardrail (ADD+DELETE 冲突 + replace 重叠)
  ├─ Section-Aware 分组
  ├─ ThreadPoolExecutor 并行 LLM 合并
  └─ Root Merge (跨 section 一致性审查)
    ↓
PatchApplyExecutor (应用 patch + 三级降级匹配)
  ├─ exact_match
  ├─ fuzzy_match (difflib)
  └─ llm_match (LLM 语义匹配)
    ↓
ToxicityTestExecutor (测毒验证)
```

### Patch Operations

| Operation | Description |
|-----------|-------------|
| `append_to_section` | 在 section 末尾追加内容 |
| `insert_after` | 在指定文本之后插入 |
| `insert_before` | 在指定文本之前插入 |
| `replace_in_section` | 替换 section 中的文本 |
| `replace_section` | 完全重写整个 section |
| `add_after_section` | 在目标 section 之后新增 section |
| `delete_section` | 删除整个 section |

## Configuration

```yaml
# configs/optimizer.yaml
models:
  extraction:
    provider: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-4o
    api_key_env: OPENAI_API_KEY
  optimizer:
    provider: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-4o
    api_key_env: OPENAI_API_KEY

optimizer:
  batch_size: 5
  max_iterations: 5
  fewshot_enabled: true

prompts:
  extraction: prompts/extraction.txt
  analysis: prompts/analysis.txt
  analysis_reflection: prompts/analysis_reflection.txt
  patch_generation: prompts/patch_generation.txt
  patch_calibration: prompts/patch_calibration.txt
  patch_merge: prompts/patch_merge.txt
  patch_root_merge: prompts/patch_root_merge.txt
  patch_text_match: prompts/patch_text_match.txt
  prompt_standardization: prompts/prompt_standardization.txt
  output_repair: prompts/output_repair.txt
```

## CLI Parameters

```bash
python -m mmap_optimizer.core.cli run \
  --data-dir data \
  --output-dir runs/output \
  --batch-size 5 \
  --rounds 3 \
  --extraction-prompt prompts/extraction.txt \
  --analysis-prompt prompts/analysis.txt \
  --analysis-reflection-prompt prompts/analysis_reflection.txt \
  --patch-generation-prompt prompts/patch_generation.txt \
  --patch-calibration-prompt prompts/patch_calibration.txt \
  --patch-merge-prompt prompts/patch_merge.txt \
  --patch-root-merge-prompt prompts/patch_root_merge.txt \
  --patch-text-match-prompt prompts/patch_text_match.txt \
  --prompt-standardization prompts/prompt_standardization.txt
```

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run core tests
python -m pytest tests/test_core.py -v

# Run new patch system tests
python -m pytest tests/test_patch_new_system.py -v
```

## Key Design Decisions

- **LLM-based merge** — Patch merge uses LLM for semantic-level deduplication, generalization, and conflict resolution, replacing the old text-concatenation approach
- **Three-level text matching** — When exact match fails for `old_text`/`target_text`, the system degrades to difflib fuzzy match, then to LLM semantic match
- **Deterministic guardrail** — Before LLM merge, deterministic checks (ADD+DELETE conflicts, replace n-gram overlaps) filter out obvious conflicts
- **Section-Aware grouping** — Patches are grouped by `target_section` for parallel processing, with single-pass for isolated patches
- **Centralized prompts** — All LLM prompts are stored in `prompts/` directory, configurable via CLI or YAML
- **Blind review** — AnalysisExecutor performs blind review without ground truth, only using image and extraction result
- **Reflection mechanism** — When blind review is incorrect, reflection is triggered with ground truth for error analysis
