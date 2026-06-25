# Plan: 基于 Section 贡献度的 LLM Prompt 压缩

## Summary

为 CompressionExecutor 引入基于 section 贡献度（EMA 追踪）的 LLM 压缩能力，替代当前的纯确定性压缩。每轮抽样测试时提取模型输出的 section 归因信息，用 EMA 累积各 section 贡献度，压缩时优先压缩低贡献 section。压缩采用混合策略（Section 级 LLM + Prompt 级 LLM），验证采用 LLM 语义验证（替代昂贵的回归测试）。

---

## Current State Analysis

### 已有的归因机制（产出但未消费）

1. **Extraction prompt**（`prompts/extraction.txt` 第33行）已要求模型输出 `used_prompt_sections: [{section_id, reason}]`，但 `ExtractionExecutor._parse_output` 只做 `json.loads`，从未提取该字段。

2. **Analysis prompt**（`prompts/analysis.txt` 第48-55行）已要求输出 `prompt_section_attribution: [{section_id, section_name, reason}]`，但仅限 INCORRECT 场景，且 `AnalysisExecutor` 从未提取该字段（埋在 `AnalysisResult.judgement` dict 中）。

3. **patch_generation** 的 `cited_sections` 写入 `patch.metadata["cited_sections"]`，全代码库只写不读。

### 当前 CompressionExecutor（`mmap_optimizer/executors/compression_executor.py`）

- 纯确定性压缩：去重连续空行、去重重复行、去除行尾空白、bullets 去重
- 不调用 LLM（`model_client` 参数接收但未使用）
- 无 prompt 文件
- 压缩后跑完整回归测试（重新抽取/分析 + 评估），成本高
- 接受标准：`post_acc >= pre_acc 且 broken_sample_ids 为空`

### 配置（`phases/prompt_optimization.py`）
- `extraction_prompt_line_limit: int = 300`, `char_limit: int = 20000`
- `analysis_prompt_line_limit: int = 250`, `char_limit: int = 16000`

### 工厂（`executors/factory.py` 第309行）
- `CompressionExecutor(model_client=model_client)` — 只传 model_client

---

## Proposed Changes

### 1. 新增 `prompts/prompt_compression.txt` — 统一压缩 prompt

融合 CONSOLIDATION_PROMPT（行数边界控制、硬性约束、压缩策略）+ LLM_PRUNE_PROMPT（section 级直接输出）的合理部分，支持 section 级和 prompt 级两种压缩模式。

**设计要点**：
- 角色定位：Prompt 结构精炼与无损压缩专家
- 输入参数：`{mode}`（section/prompt）、`{section_header}`、`{section_content}`（section 模式）/ `{current_prompt}`（prompt 模式）、`{current_lines}`、`{min_target_lines}`、`{max_target_lines}`
- 硬性约束：双向边界死线、逻辑资产保全、零幻觉
- 合法压缩手段：语义去噪、高密度句式重组、多维列表收拢、历史残留清洗
- 工作流：宏观控率 → 动态脱水 → 行数逆向回补
- 输出：直接输出精炼后文本，禁止 Markdown 包裹

### 2. 新增 `prompts/prompt_compression_validation.txt` — 压缩验证 prompt

基于 LLM_PRUNE_VALIDATION_PROMPT，对比原始文本与精简文本，校验语义完整性、约束一致性、逻辑无歧义。

**设计要点**：
- 输入：`{original_section}`、`{pruned_section}`
- 三项审计标准：语义完整性、约束一致性、逻辑与消除歧义
- 输出：JSON `{"valid": true/false, "reason": "..."}`

### 3. 新增 `mmap_optimizer/prompt/section_contribution.py` — Section 贡献度追踪器

```python
class SectionContributionTracker:
    """追踪各 section 的 EMA 贡献度。"""

    def __init__(self, alpha: float = 0.3):
        self.alpha = alpha  # EMA 平滑因子
        self._ema: dict[str, float] = {}  # section_id -> ema score [-1, 1]

    def update(self, batch_attribution: dict[str, list[dict]], batch_results: dict[str, bool]) -> None:
        """一轮 batch 后更新 EMA。
        
        Args:
            batch_attribution: {sample_id: [{section_id, reason}, ...]}
            batch_results: {sample_id: is_correct}
        """
        # 计算本轮各 section 的 batch 平均贡献度
        # correct 样本引用的 section: +1, incorrect 样本引用的 section: -1
        # frequency[section] = (positive_count - negative_count) / total_samples
        # ema[section] = alpha * frequency + (1-alpha) * ema[section]

    def get_contribution(self, section_id: str) -> float:
        """获取 section 的 EMA 贡献度，未追踪返回 0.0。"""

    def get_priority_order(self, section_ids: list[str]) -> list[str]:
        """返回按贡献度升序排列的 section_id 列表（低贡献在前，优先压缩）。"""

    def to_dict(self) -> dict[str, float]:
        """序列化。"""

    @classmethod
    def from_dict(cls, data: dict, alpha: float = 0.3) -> "SectionContributionTracker":
        """反序列化。"""
```

### 4. 修改 `prompts/analysis.txt` — 归因输出扩展为全场景

**变更**：将第24行 `# 归因分析（仅当 INCORRECT 时）` 改为 `# 归因分析（所有情况）`
- CORRECT：归因到促成正确的关键 section
- INCORRECT：归因到导致错误的 section
- UNCERTAIN：归因到信息不足相关的 section

### 5. 修改 `mmap_optimizer/executors/analysis_executor.py` — 提取归因字段

新增 `_extract_prompt_section_attribution` 方法，从 `judgement` dict 中提取 `prompt_section_attribution`，返回 `list[dict]`。
在 `execute` 方法中调用，将结果存入 `AnalysisResult.judgement`（已有，无需改 dataclass）。

### 6. 修改 `mmap_optimizer/executors/extraction_executor.py` — 提取归因字段

在 `_parse_output` 返回的 `parsed_output` dict 中，`used_prompt_sections` 字段已自然存在。无需额外提取，调用方（stage）可直接从 `ExtractionResult.parsed_output["used_prompt_sections"]` 读取。

### 7. 修改 `mmap_optimizer/stages/extraction_prompt_optimization.py` — 集成贡献度追踪

- 在 `__init__` 中新增 `self.contribution_tracker = SectionContributionTracker(alpha=...)`
- 在 Step 1（base extraction）和 Step 9（final extraction）后，从 `ExtractionResult.parsed_output` 提取 `used_prompt_sections`，结合 `EvalRecord.correct` 更新 tracker
- 在 Step 8（`_step8_compress_if_needed`）中，将 `self.contribution_tracker` 传入 `compress_if_needed`
- 从 `CompressionReport` 中移除回归测试相关字段

### 8. 修改 `mmap_optimizer/stages/analysis_prompt_optimization.py` — 集成贡献度追踪

- 在 `__init__` 中新增 `self.contribution_tracker = SectionContributionTracker(alpha=...)`
- 在 Step 1（base analysis）后，从 `AnalysisResult.judgement["prompt_section_attribution"]` 提取归因，结合 `analysis_correct` 更新 tracker
- 在 Step 7（`_step7_compress_if_needed`）中，将 `self.contribution_tracker` 传入 `compress_if_needed`

### 9. 重写 `mmap_optimizer/executors/compression_executor.py` — 混合 LLM 压缩

**新 `__init__` 签名**：
```python
def __init__(
    self,
    model_client: Any = None,
    model_config: dict[str, Any] | None = None,
    compression_prompt_path: str = "prompts/prompt_compression.txt",
    validation_prompt_path: str = "prompts/prompt_compression_validation.txt",
    ema_alpha: float = 0.3,
) -> None:
```

**新 `compress_if_needed` 签名**：
```python
def compress_if_needed(
    self,
    prompt: StructuredPrompt,
    line_limit: int,
    char_limit: int,
    batch: SampleBatch,
    sample_set: SampleSet,
    mode: str = "extraction",
    contribution_tracker: SectionContributionTracker | None = None,
    # 移除 extraction_executor / evaluation_executor / analysis_executor 等回归测试参数
) -> tuple[StructuredPrompt, CompressionReport]:
```

**新压缩流程（4 阶段）**：

```
Step 1: 统计行数和字符数
  ↓
Step 2: 检查是否需要压缩（超限才继续）
  ↓
Step 3: 确定性预压缩（保留现有 _compress_content）
  ├─ 去重空行、重复行、行尾空白
  └─ 检查是否已降至限内 → 是则接受
  ↓
Step 4: Section 级 LLM 压缩（低贡献优先）
  ├─ 从 contribution_tracker 获取 section 优先级排序
  ├─ 对低贡献 mutable section 逐个调用 LLM 压缩
  ├─ 每个 section 压缩后用 LLM 验证语义无损
  ├─ 验证失败则回退该 section
  └─ 检查是否已降至限内 → 是则接受
  ↓
Step 5: Prompt 级 LLM 压缩（仍超限时的兜底）
  ├─ 将整个 prompt + 行数预算发给 LLM 整体压缩
  ├─ LLM 验证语义无损
  └─ 验证失败则回退
  ↓
Step 6: 接受/拒绝
  ├─ LLM 验证通过 → 接受
  └─ 验证失败 → 拒绝 (VALIDATION_FAILED)
```

**新增方法**：
- `_llm_compress_section(section: PromptSection, current_lines: int, target_lines: tuple[int, int]) -> str | None` — 调用 LLM 压缩单个 section
- `_llm_compress_prompt(prompt: StructuredPrompt, current_lines: int, target_lines: tuple[int, int]) -> str | None` — 调用 LLM 压缩整个 prompt
- `_llm_validate_compression(original: str, compressed: str) -> bool` — 调用 LLM 验证语义等价
- `_compute_target_lines(current_lines: int, limit: int) -> tuple[int, int]` — 计算目标行数区间

**移除方法**：
- `_run_extraction_regression` — 回归测试
- `_run_analysis_regression` — 回归测试

**修改 CompressionReport**（`patch/types.py`）：
- 移除：`pre_compression_accuracy`、`post_compression_accuracy`、`broken_sample_ids`、`fixed_sample_ids`
- 新增：`validation_passed: bool = False`、`validation_reasons: list[str] = field(default_factory=list)`
- 保留：`triggered`、`accepted`、`rejected_reason`、`line_count_before/after`、`char_count_before/after`、`compressed_prompt_id`、`still_over_limit`、`warnings`
- 新增：`compressed_sections: list[str] = field(default_factory=list)`（记录哪些 section 被压缩）

### 10. 修改 `mmap_optimizer/executors/factory.py` — 传入新参数

```python
"compression": CompressionExecutor(
    model_client=model_client,
    model_config=optimizer_model_config,
    compression_prompt_path=prompts_config.prompt_compression,
    validation_prompt_path=prompts_config.prompt_compression_validation,
    ema_alpha=prompt_optimization_config.ema_alpha,
),
```

### 11. 修改 `mmap_optimizer/core/config.py` — 新增配置

**PromptsConfig 新增**：
- `prompt_compression: str = "prompts/prompt_compression.txt"`
- `prompt_compression_validation: str = "prompts/prompt_compression_validation.txt"`

**PromptOptimizationConfig 新增**：
- `ema_alpha: float = 0.3` — EMA 平滑因子

### 12. 修改 `mmap_optimizer/phases/prompt_optimization.py` — 新增配置字段

`PromptOptimizationConfig` 新增 `ema_alpha: float = 0.3`。

### 13. 修改 `mmap_optimizer/stages/extraction_prompt_optimization.py` 和 `analysis_prompt_optimization.py` — 适配新 compress_if_needed 签名

移除传入 `extraction_executor`、`evaluation_executor`、`analysis_executor`、`extraction_results`、`extraction_prompt`、`pre_compression_eval_records`、`pre_compression_analysis_results` 等回归测试参数，改为传入 `contribution_tracker`。

---

## Assumptions & Decisions

1. **归因来源**：extraction 用 `parsed_output["used_prompt_sections"]`（prompt 已有），analysis 用 `judgement["prompt_section_attribution"]`（prompt 已有但需改为全场景输出）。
2. **EMA 计算**：correct 样本引用的 section = +1，incorrect 样本引用的 section = -1，UNCERTAIN = 0。每轮 batch 计算平均频率后做 EMA 平滑。alpha=0.3。
3. **压缩优先级**：按 EMA 贡献度升序排列，低贡献（或负贡献）的 section 优先压缩，高贡献 section 尽量不动。
4. **压缩策略**：确定性预压缩 → Section 级 LLM 压缩（低贡献优先）→ Prompt 级 LLM 压缩（兜底）。
5. **验证方式**：LLM 语义验证（替代回归测试），验证失败的 section 回退原内容。
6. **统一 prompt**：extraction 和 analysis 共用同一个压缩 prompt。
7. **CompressionReport 简化**：移除回归测试相关字段，新增验证结果字段。
8. **不可压缩 section**：immutable section 不参与任何 LLM 压缩（保留现有约束）。
9. **目标行数区间**：section 级压缩目标为原行数的 50%-80%；prompt 级压缩目标为 `[line_limit * 0.85, line_limit]`。

---

## Verification Steps

1. **单元测试**：
   - `SectionContributionTracker` 的 update / get_contribution / get_priority_order / 序列化
   - `CompressionExecutor` 确定性预压缩（保持现有测试通过）
   - `CompressionExecutor` LLM section 级压缩（mock model_client）
   - `CompressionExecutor` LLM prompt 级压缩（mock model_client）
   - `CompressionExecutor` LLM 验证（mock model_client）
   - `CompressionExecutor` 验证失败回退
   - `CompressionExecutor` 无 contribution_tracker 时的降级（按 section 顺序压缩）

2. **集成测试**：
   - extraction 优化流程中 contribution_tracker 正确更新
   - analysis 优化流程中 contribution_tracker 正确更新
   - 压缩后 prompt 行数降至限内
   - 压缩后 immutable section 内容不变

3. **回归测试**：
   - 现有 34 个测试全部通过
   - `test_pr4_compression_executor.py` 适配新接口

4. **Prompt 文件验证**：
   - `prompt_compression.txt` 含 mode/section_header/section_content/current_prompt/current_lines/min_target_lines/max_target_lines 占位符
   - `prompt_compression_validation.txt` 含 original_section/pruned_section 占位符

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `prompts/prompt_compression.txt` | 新增 | 统一压缩 prompt（section 级 + prompt 级） |
| `prompts/prompt_compression_validation.txt` | 新增 | 压缩验证 prompt |
| `mmap_optimizer/prompt/section_contribution.py` | 新增 | SectionContributionTracker |
| `prompts/analysis.txt` | 修改 | 归因输出扩展为全场景 |
| `mmap_optimizer/executors/compression_executor.py` | 重写 | 混合 LLM 压缩 + LLM 验证 |
| `mmap_optimizer/executors/analysis_executor.py` | 修改 | 提取 prompt_section_attribution |
| `mmap_optimizer/executors/factory.py` | 修改 | 传入新参数 |
| `mmap_optimizer/patch/types.py` | 修改 | CompressionReport 字段调整 |
| `mmap_optimizer/core/config.py` | 修改 | 新增 prompt_compression/ema_alpha 配置 |
| `mmap_optimizer/phases/prompt_optimization.py` | 修改 | 新增 ema_alpha 字段 |
| `mmap_optimizer/stages/extraction_prompt_optimization.py` | 修改 | 集成贡献度追踪 + 适配新压缩接口 |
| `mmap_optimizer/stages/analysis_prompt_optimization.py` | 修改 | 集成贡献度追踪 + 适配新压缩接口 |
| `tests/test_patch_new_system.py` | 修改 | 新增贡献度追踪 + LLM 压缩测试 |
