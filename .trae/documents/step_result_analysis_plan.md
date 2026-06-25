# 抽取 Step 结果输出分析

## 一、核心数据结构

项目中的"step 结果"主要分为两层：

### 1. 阶段输出结果（每个 Step 的输出）

| 结果类型 | 数据类 | 文件 |
|---------|--------|------|
| 抽取结果 | `ExtractionResult` | [extraction_prompt_optimization.py#L13-L30](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py#L13-L30) |
| 评估记录 | `EvalRecord` | [extraction_prompt_optimization.py#L53-L70](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py#L53-L70) |
| 分析结果 | `AnalysisResult` | [extraction_prompt_optimization.py#L33-L50](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py#L33-L50) |
| Patch 草案 | `ExtractionPatch` / `AnalysisPatch` | [patch/types.py#L17-L108](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/patch/types.py#L17-L108) |
| 合并报告 | `PatchMergeReport` | [patch/types.py#L111-L150](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/patch/types.py#L111-L150) |
| 压缩报告 | `CompressionReport` | patch/types.py |
| 毒性测试报告 | `ToxicityReport` | patch/types.py |

### 2. 阶段级指标

| 指标类 | 文件 |
|--------|------|
| `ExtractionMetrics` | [extraction_prompt_optimization.py#L73-L108](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py#L73-L108) |
| `AnalysisMetrics` | stages/analysis_prompt_optimization.py |

---

## 二、StepResult 在 Stage 中的流转

以 `ExtractionPromptOptimizationStage` 为例，每个 Step 的输入输出如下：

| Step | 方法 | 输出结果 |
|------|------|---------|
| Step 1 | `_step1_execute_extraction` | `base_extraction_results: list[ExtractionResult]` |
| Step 2 | `_step2_compute_base_metrics` | 更新 `metrics` (base_accuracy) |
| Step 3 | `_step3_analyze_results` | `analysis_results: list[AnalysisResult]` |
| Step 4 | `_step4_generate_patches` | `draft_patches: list[ExtractionPatch]` |
| Step 5 | `_step5_initial_merge` | `initial_merged_patches: list[ExtractionPatch]` + `initial_merge_report` |
| Step 6 | `_step6_apply_and_test` | `validated_patches: list[ExtractionPatch]` + `rejected_patches: list[ExtractionPatch]` |
| Step 7 | `_step7_regression_and_toxicity_test` | `safe_patches: list[ExtractionPatch]` + `toxic_patches: list[ExtractionPatch]` + `toxicity_report` |
| Step 8 | `_step8_compress_if_needed` | `final_merged_patches: list[ExtractionPatch]` + `compression_report` |
| Step 9 | `_step9_final_test_and_metrics` | `final_extraction_results: list[ExtractionResult]` + `final_eval_records: list[EvalRecord]` |

---

## 三、关键结果数据结构详解

### 3.1 ExtractionResult（抽取结果）

```python
@dataclass
class ExtractionResult:
    sample_id: str
    raw_output: str
    parsed_output: dict | None
    status: Literal["correct", "wrong", "invalid"]
    error_details: list[str] = field(default_factory=list)
```

| 字段 | 说明 |
|------|------|
| `sample_id` | 样本唯一标识 |
| `raw_output` | 模型原始输出 |
| `parsed_output` | 解析后的 dict（解析失败为 None） |
| `status` | correct / wrong / invalid（invalid 表示解析失败） |
| `error_details` | 错误详情列表 |

### 3.2 EvalRecord（评估记录）

```python
@dataclass
class EvalRecord:
    sample_id: str
    extraction_result_id: str
    status: str
    correct: bool
    details: dict[str, Any] = field(default_factory=dict)
```

### 3.3 AnalysisResult（分析结果）

```python
@dataclass
class AnalysisResult:
    sample_id: str
    judgement: dict[str, Any]
    analysis_correct: bool
    error_reason: str | None = None
    patch_suggestion: dict[str, Any] | None = None
```

### 3.4 ExtractionPatch（Patch 草案）

```python
@dataclass
class ExtractionPatch:
    id: str
    target_section_id: str
    operation_type: Literal["replace", "insert_before", "insert_after", "delete"]
    content: str
    rationale: str
    source_sample_ids: list[str]
    status: Literal["draft", "merged", "candidate_safe", "accepted", "rejected"]
    rejection_reason: str | None = None
    fixed_sample_ids: list[str]
    broken_sample_ids: list[str]
    toxic_sample_ids: list[str]
    metadata: dict[str, Any]
```

**Status 状态流转**：
- `draft` → 初始生成
- `merged` → 已合并
- `candidate_safe` → 通过安全测试
- `accepted` → 最终接受
- `rejected` → 拒绝

### 3.5 ExtractionMetrics（阶段指标）

```python
@dataclass
class ExtractionMetrics:
    base_accuracy: float | None = None
    final_accuracy: float | None = None
    base_correct_count: int = 0
    base_wrong_count: int = 0
    base_invalid_count: int = 0
    final_correct_count: int = 0
    final_wrong_count: int = 0
    final_invalid_count: int = 0
    accepted_patch_count: int = 0
    rejected_patch_count: int = 0
    toxic_patch_count: int = 0
    compression_accepted: bool = False
    rollback: bool = False
    no_progress: bool = False
```

### 3.6 PatchMergeReport（合并报告）

```python
@dataclass
class PatchMergeReport:
    id: str
    input_patch_count: int
    merged_patch_count: int
    conflict_count: int
    merged_patches: list[dict]
    conflicts: list[dict]
    strategy: str = "tree_merge"
    dropped_patch_count: int
    input_patch_ids: list[str]
    merged_patch_ids: list[str]
    dropped_patch_ids: list[str]
    conflict_patch_ids: list[str]
    merge_reason: str
    fallback_used: bool
    warnings: list[str]
```

---

## 四、数据流向图

```
Step 1: 抽取
  输入: extraction_prompt + batch + sample_set
  输出: base_extraction_results (ExtractionResult[])
        ↓
Step 2: 计算基线指标
  输入: base_extraction_results + ground_truth
  输出: base_eval_records + metrics (base_accuracy)
        ↓
Step 3: 分析失败样本
  输入: base_extraction_results + base_eval_records
  输出: analysis_results (AnalysisResult[])
        ↓
Step 4: 生成 Patch
  输入: analysis_results
  输出: draft_patches (ExtractionPatch[])
        ↓
Step 5: 初始合并
  输入: draft_patches
  输出: initial_merged_patches + initial_merge_report
        ↓
Step 6: 应用与测试
  输入: initial_merged_patches + trial_prompt + batch
  输出: validated_patches + rejected_patches + patched_eval_records
        ↓
Step 7: 回归与毒性测试
  输入: validated_patches + sample_set
  输出: safe_patches + toxic_patches + toxicity_report
        ↓
Step 8: 压缩
  输入: safe_patches
  输出: final_merged_patches + compression_report
        ↓
Step 9: 最终测试与指标
  输入: final_merged_patches + sample_set
  输出: final_extraction_results + final_eval_records + final metrics
```

---

## 五、序列化支持

所有结果数据结构都支持 `to_dict()` / `from_dict()` 方法，可用于：
- 持久化到文件
- 网络传输
- 日志记录
- 测试验证

## 六、文件清单

| 文件 | 包含的数据结构 |
|------|---------------|
| [stages/extraction_prompt_optimization.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py) | `ExtractionResult`, `AnalysisResult`, `EvalRecord`, `ExtractionMetrics` |
| [stages/analysis_prompt_optimization.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/analysis_prompt_optimization.py) | `ReflectionResult`, `AnalysisMetrics` |
| [patch/types.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/patch/types.py) | `ExtractionPatch`, `AnalysisPatch`, `PatchMergeReport`, `CompressionReport`, `ToxicityReport` |