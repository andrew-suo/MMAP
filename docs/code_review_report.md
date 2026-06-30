# MMAP 代码深度逻辑走读分析报告

> 生成日期：2026-06-29
> 审查范围：`mmap_optimizer` 全部 4 个核心模块，共 40+ 个文件

---

## 一、审查范围

本次审查覆盖以下模块：

| 模块 | 文件数 | 核心职责 |
|------|--------|----------|
| **core** | 7 | 运行器、配置、检查点、CLI、工件管理、日志、进度 |
| **executors** | 12 | 抽取、评估、分析、Patch 生成/应用/验证/合并、Few-shot、测毒、压缩 |
| **patch/model** | 10 | Patch 聚类、冲突检测、去重、树归约、模型客户端、重试 |
| **phases/stages/data/prompt** | 13 | 提示优化阶段、抽取/分析优化阶段、数据集加载、采样、提示结构、输出修复 |

---

## 二、问题汇总

| 严重程度 | 数量 | 模块分布 |
|---------|------|----------|
| 🔴 高 | 10 | core(1) + executors(4) + patch/model(0) + phases/stages(5) |
| 🟡 中 | 22 | core(6) + executors(11) + patch/model(4) + phases/stages(8) |
| 🟢 低 | 18 | 全模块 |

---

## 三、高严重度问题（必须优先修复）

### 问题 1：Resume 后 Run Summary 累计统计全部丢失

- **位置**：`mmap_optimizer/core/runner.py:619-693`
- **类型**：业务规则实现错误 / 状态管理缺陷
- **描述**：`PromptOptimizationPhase` 在 resume 时全新构造，`iteration_results` 初始为空。`phase.run(start_iteration=N)` 只 append 新迭代，导致 `po_summary.iterations`、`total_accepted_patches`、`best_accuracy`、`base_accuracy_first` 全部只反映本次新跑的迭代，不包含历史。
- **影响**：Resume 后 `run_summary.json` 中迭代数、patch 总数、最佳准确率全部错误（偏小）。CLI 输出误导用户。

### 问题 2：Extraction 模式下缺失样本导致所有 patch 被误判为 toxic

- **位置**：`mmap_optimizer/executors/toxicity_executor.py:304-334`
- **类型**：条件分支覆盖 / 边界条件
- **描述**：`_test_single_sample` 在 extraction 模式下，若 `toxic_sample_ids` 包含不存在于 `sample_set` 的 sample_id，`spec` 为 None，`ExtractionExecutor.execute` 会 `continue` 跳过，导致 `extraction_results` 为空，`return True`（broken）→ patch 被拒绝为 toxic。对比 analysis 模式有 `if spec is None: return False` 保护。
- **影响**：只要 `toxic_sample_ids` 包含一个不存在的 ID，**每个候选 patch 都会被误判为 toxic**，整个 patch 优化流程产出为空。

### 问题 3：Extraction/Analysis Executor 缺失时静默放行所有 patch

- **位置**：`mmap_optimizer/executors/toxicity_executor.py:318-319, 337-338`
- **类型**：错误处理 / 失败开放（fail-open）
- **描述**：当 `extraction_executor` 或 `analysis_executor` 为 None 时，直接 `return False`（未 break），所有 patch 被判为 safe。
- **影响**：配置错误遗漏 executor 时，测毒环节完全跳过，所有 patch（包括真正有毒的）都会被放行，可能破坏已有正确样本。

### 问题 4：Provenance 校验失败时丢弃所有输入 patch

- **位置**：`mmap_optimizer/executors/merge_executor.py:263-284`
- **类型**：业务规则 / 状态一致性
- **描述**：当 LLM 返回的 merged_dict 的 `source_patch_ids` 全部无效时，将**所有原始 patch** 标记为 rejected。同一 patch 同时出现在 `merged_patches`（通过合并后代）和 `dropped_patches`（原始引用）中，状态不一致。
- **影响**：LLM 一次异常输出导致全部输入 patch 被丢弃，merge 结果为空。

### 问题 5：测毒循环中无异常处理，单次模型失败导致整个测毒崩溃

- **位置**：`mmap_optimizer/executors/toxicity_executor.py:198-219`
- **类型**：异常处理缺失
- **描述**：`_test_single_sample` 调用 `extraction_executor.execute()`，但循环体没有 try/except 包裹。单次模型调用失败（网络超时、API 限流）会中断整个测毒循环，已完成的结果丢失。
- **影响**：测毒阶段单次失败导致整个测毒崩溃，`ToxicityReport` 无法生成。

### 问题 6：Few-shot 阶段 artifact 永远写入空文件

- **位置**：`mmap_optimizer/phases/fewshot_optimization.py:601,609`
- **类型**：变量初始化与赋值逻辑
- **描述**：`FewshotOptimizationIterationResult` 不存在 `base_results`、`base_eval_records`、`final_results`、`final_eval_records` 属性，但保存逻辑使用 `getattr(result, "base_results", [])` 等，永远返回空列表。
- **影响**：`fewshot/iteration_X/fewshot/` 下四个 artifact 文件永远为空，过程数据完全丢失，无法用于 debug/resume。

### 问题 7：Markdown 解析丢失代码块结束标记，未闭合代码块丢失全部内容

- **位置**：`mmap_optimizer/phases/prompt_structuring.py:56-70`
- **类型**：条件分支覆盖
- **描述**：关闭代码块时未加入结束 ` ``` ` 标记；文件结束时 `in_code_block` 仍为 True，`code_block_content` 不被处理，整个代码块内容丢失。
- **影响**：含代码块的 prompt（JSON schema 示例、Python 代码片段）经结构化解析后语义被破坏。

### 问题 8：Prompt 标准化质量回退检查只看 section 数量，不看质量

- **位置**：`mmap_optimizer/phases/prompt_structuring.py:253-272`
- **类型**：条件分支覆盖
- **描述**：只检查 `len(new_structured.sections)` 数量回退，不检查质量退化。标准化后 section 数量 ≥ 原数量但质量从 "good" 退化到 "poor" 时，代码直接接受劣化结果。
- **影响**：系统接受质量更差的结构化 prompt，后续优化基于劣化结构运行。

### 问题 9：Section 贡献度追踪器硬编码 alpha，忽略 ema_alpha 配置

- **位置**：`mmap_optimizer/stages/extraction_prompt_optimization.py:213, analysis_prompt_optimization.py:155`
- **类型**：函数调用参数传递
- **描述**：两个 Stage 的 `__init__` 接收 `ema_alpha` 参数并存入 `self.ema_alpha`，但初始化 `SectionContributionTracker` 时写死 `alpha=0.3`。`PromptOptimizationConfig.ema_alpha` 的值从未传递给 tracker。
- **影响**：用户通过配置调整 `ema_alpha` 完全不生效，压缩阶段 section 优先级始终用 0.3。

### 问题 10：Extraction Stage 缺少 regression 准确率检查

- **位置**：`mmap_optimizer/stages/extraction_prompt_optimization.py:855-880`
- **类型**：条件分支覆盖 / 业务规则
- **描述**：在「有 `patch_apply_executor` 但无 `toxicity_test_executor`」分支中，只要 `fixed_count > 0` 且无 broken 就接受，**不检查 `patched_accuracy >= base_accuracy`**。而 Analysis Stage 同等场景有 regression 检查。
- **影响**：Extraction Stage 会接受「修了 1 个样本但整体准确率下降」的 patch 集合，extraction prompt 被劣化更新。

---

## 四、中严重度问题（关键功能正确性）

### 4.1 Core 模块

**问题 11**: `ap_summary.rollback_count` 永远为 0
- 位置：`mmap_optimizer/core/runner.py:644-649`
- 描述：`AnalysisMetrics` 没有 `rollback` 字段，但 runner 只基于 `result.rollback`（来自 extraction）累加，不处理 analysis 的 rollback。

**问题 12**: Resume 后 `duration_seconds` 与 `start_time`/`end_time` 不一致
- 位置：`mmap_optimizer/core/runner.py:405-468`
- 描述：resume 后 `start_time` 是原始 run 的开始时间，`end_time` 是本次结束时间，但 `duration_seconds` 只算了本次 session 的时长。

**问题 13**: `_save_checkpoint` 直接覆盖 `current_iteration`/`current_stage`
- 位置：`mmap_optimizer/core/runner.py:848-849`
- 描述：`current_phase` 和 `current_step_id` 使用 `or` 守卫保留旧值，但 `current_iteration` 和 `current_stage` 直接赋值，resume 后被 None 覆盖。

**问题 14**: Phase 执行期间异常未捕获，checkpoint 不记录 `last_error`
- 位置：`mmap_optimizer/core/runner.py:433-458`
- 描述：调用三个 phase 执行函数时没有 try/except 包裹，异常会直接传播，导致 checkpoint 的 `last_error` 始终为 None。

**问题 15**: `use_mock`/`progress_enabled` 未做布尔归一化
- 位置：`mmap_optimizer/core/config.py:277,279`
- 描述：当 YAML 模块不可用而走简单解析器时，带引号的布尔值会被解析为字符串，导致逻辑错误。

**问题 16**: Fewshot sampler 配置除 `type` 外字段被静默丢弃
- 位置：`mmap_optimizer/core/config.py:400-403`
- 描述：`from_dict` 构造 `FewshotConfig.sampler` 时只读 `type`，其他字段被忽略。

### 4.2 Executors 模块

**问题 17**: `_last_parse_record` 残留导致脏数据归因到错误样本
- 位置：`mmap_optimizer/executors/analysis_executor.py:387-411`
- 描述：`_parse_judgement` 在 `raw_output` 为空时提前返回 `{}`，不更新 `self._last_parse_record`，导致上一轮的解析记录被错误地归因到当前样本。

**问题 18**: `_call_patch_generation_model` 静默吞没所有异常
- 位置：`mmap_optimizer/executors/patch_generation_executor.py:269-296`
- 描述：prompt 文件读取错误和模型调用失败都被静默忽略，返回空列表。

**问题 19**: 缺失字段在 parsed_output 和 ground_truth 中同时不存在时被判定为匹配
- 位置：`mmap_optimizer/executors/evaluation_executor.py:70-75`
- 描述：`None == None` 为 True，导致同时缺失的字段被判为匹配。

**问题 20**: `primary_answer_fields` 为空时所有抽取结果被判定为 correct
- 位置：`mmap_optimizer/executors/evaluation_executor.py:66-91`
- 描述：空列表循环不执行，`all_match` 保持 `True`，`status = "correct"`。

**问题 21**: 合并后 target_section 为歧义标题时 patch 使用非法 section ID
- 位置：`mmap_optimizer/executors/merge_executor.py:512-519`
- 描述：`_normalize_merged_target_section` 在标题歧义时返回空的 `normalized_target_section`，但后续仍使用原始标题文本作为 section ID。

**问题 22**: reflection status 展示逻辑语义反转
- 位置：`mmap_optimizer/executors/patch_generation_executor.py:412`
- 描述：`reflection_success=True` 映射为 "INCORRECT"，语义反转。

**问题 23**: `model_output_repairs` 列表跨批次无限增长
- 位置：`mmap_optimizer/executors/analysis_executor.py:54`
- 描述：`AnalysisExecutor` 和 `ExtractionExecutor` 持续 append 但没有重置方法，内存持续增长。

**问题 24**: `apply()` 未处理 `patches=None`
- 位置：`mmap_optimizer/executors/patch_apply_executor.py:141-144`
- 描述：`not patches` 对 `None` 和空列表都返回 True，但 `for patch in patches` 对 `None` 会抛出 `TypeError`。

**问题 25**: `_llm_compress_sections` 原地修改输入 prompt + `str.format` 模板安全
- 位置：`mmap_optimizer/executors/compression_executor.py:317-349`
- 描述：直接修改传入 prompt 的 section 内容；`str.format` 对含字面花括号的模板会抛出 KeyError。

**问题 26**: `_calibrate_patches` 宽泛异常捕获掩盖所有错误
- 位置：`mmap_optimizer/executors/patch_validator.py:296-298`
- 描述：所有异常被 `except Exception` 捕获后静默返回原 patch，无日志记录。

**问题 27**: ToxicityTestExecutor/CompressionExecutor 接口签名与 Protocol 不一致
- 描述：Protocol 参数顺序、可选性、返回类型与实际实现不匹配。

### 4.3 Patch/Model 模块

**问题 28**: `prev_count` 终止条件比较基准滞后一轮
- 位置：`mmap_optimizer/patch/tree_reduce.py:113,121`
- 描述：`prev_count` 赋值在 `current` 更新之前，导致终止条件比较的是本轮输出 vs 上一轮输入。

**问题 29**: `detect_replace_overlaps` 传递性重叠导致过度删除
- 位置：`mmap_optimizer/patch/conflict.py:164-196`
- 描述：两两比较中立即标记删除，但当 `patch_i` 后续被更长的 `patch_k` 删除时，之前因与 `patch_i` 重叠而被删除的 `patch_j` 不会被恢复。

**问题 30**: `fuzzy_match` 滑动窗口算法性能退化为指数级
- 位置：`mmap_optimizer/patch/text_matcher.py:86-96`
- 描述：三层嵌套循环（窗口大小 × 起始位置 × SequenceMatcher），对长文本性能急剧退化。

**问题 31**: `_backfill_group_provenance` 对 None 值字段迭代崩溃
- 位置：`mmap_optimizer/patch/tree_reduce.py:358-377`
- 描述：`patch.get("source_sample_ids", [])` 当字段存在但值为 `None` 时返回 `None`，`for ... in None` 抛出 `TypeError`。

### 4.4 Phases/Stages/Data/Prompt 模块

**问题 32**: rollback 标志错误包含 extraction no_progress
- 位置：`mmap_optimizer/phases/prompt_optimization.py:278-279`
- 描述：`rollback = extraction_metrics.rollback or extraction_metrics.no_progress` 将"无进展"误标为"回滚"。

**问题 33**: Analysis Stage 出现任意 broken 样本时将所有 patch 标记为 TOXIC
- 位置：`mmap_optimizer/stages/analysis_prompt_optimization.py:712-716`
- 描述：当 `broken_ids` 非空时，将所有 patch 的 `rejection_reason` 设为 `"TOXIC"`，不区分哪个 patch 实际导致了 broken。

**问题 34**: `_standardize_with_model` 静默吞没所有异常
- 位置：`mmap_optimizer/phases/prompt_structuring.py:313-315`
- 描述：`except Exception as exc: return None` 捕获所有异常但既不记录日志也不向上传播。

**问题 35**: `PromptManager.render_prompt` 对模板中的字面花括号会抛出 KeyError/ValueError
- 位置：`mmap_optimizer/prompt/prompt_manager.py:52-56`
- 描述：`template.format(**kwargs)` 对含字面 `{`/`}` 的模板会解释为占位符。

**问题 36**: `dataset_loader` 多行无 id 的样本会合并到同一个 "unknown" sample_id
- 位置：`mmap_optimizer/data/dataset_loader.py:34-35`
- 描述：无 id 行的 `sample_id` 都设为 `"unknown"`，导致多个样本的 asset 关联到同一个 id。

**问题 37**: `repair_json_output` 对已正确解析的输出也返回 "repaired" 状态
- 位置：`mmap_optimizer/prompt/output_repair.py:160-164`
- 描述：当 `result.status == "parsed"`（无需修复）时，返回状态 `"repaired"`，与 docstring 语义不符。

**问题 38**: Few-shot `_select_difficult_samples` 补齐逻辑无法应对 batch 小于 slot_count
- 位置：`mmap_optimizer/phases/fewshot_optimization.py:534-560`
- 描述：当 `len(batch.sample_ids) < slot_count` 时，切片返回空列表，补齐循环无可选样本。

**问题 39**: Extraction Stage 使用的 base_status 真值判断与 Analysis Stage 不一致
- 位置：`mmap_optimizer/stages/extraction_prompt_optimization.py:1557-1559`
- 描述：使用 `if base_status_by_sample.get(sample_id):`（真值判断），而 Analysis Stage 使用 `if sample_id in base_status_by_sample:`。

---

## 五、低严重度问题

### 5.1 Core 模块
- **问题 40**: `RunCheckpoint.from_dict` / `RunPlan.from_dict` 对 `null` 值调用 `int()` 会崩溃
- **问题 41**: `_save_initial_artifacts` 在 `yaml` 不可用时把 JSON 内容写入 `.yaml` 文件
- **问题 42**: `to_artifact_data` 对空 dict 和空 list 处理不一致
- **问题 43**: `_save_checkpoint` 用 `or` 守卫导致无法主动清空 `current_phase`/`current_step_id`
- **问题 44**: `_safe_log_dict` 敏感键匹配只做精确匹配，子串变体漏检
- **问题 45**: 多处方法内 `import json` 未使用

### 5.2 Executors 模块
- **问题 46**: `_parallel_merge` 文档字符串与返回值数量不一致
- **问题 47**: `wrong_count` 永远为 0，状态统计为死代码
- **问题 48**: `_llm_compress_sections` 返回值被立即覆盖

### 5.3 Patch/Model 模块
- **问题 49**: 5 个 JSON 容错静态方法为死代码
- **问题 50**: 全局回退后 `failure_count` 未重置
- **问题 51**: `_root_merge` 缺少膨胀检测和重试机制
- **问题 52**: `complete_multimodal` 当 `assets=None` 时 `len()` 崩溃
- **问题 53**: `_should_retry` 对 `code=0` 的边界处理缺陷
- **问题 54**: `ToxicityReport` alias 字段冗余可能导致数据不一致

### 5.4 Phases/Stages/Data/Prompt 模块
- **问题 55**: Few-shot `sample_traces.jsonl` 保存字段不完整
- **问题 56**: `dataset_loader` 单行非法 JSON 导致整个加载失败
- **问题 57**: `BalancedTraceSampler.add_from` 中的限额检查是 O(n²)
- **问题 58**: `BatchSizeController.from_dict` 缺少类型校验
- **问题 59**: `prompt_optimization.py` 使用 `result.batch.__dict__` 而非 `to_dict()`

---

## 六、关键流程影响链路

```
Prompt Structuring
    ├─ 问题7: 代码块丢失
    └─ 问题8: 质量回退检查缺失
            │
            ▼
    Prompt Optimization
    ├─ 问题9: ema_alpha 失效
    ├─ 问题32: rollback 误标
    │       │
    │       ├─► Extraction Stage ── 问题10: 缺 regression 检查 ──► prompt 劣化
    │       └─► Analysis Stage ── 问题33: TOXIC 误标 ──► prompt 劣化
    │
    ▼
    Patch Generation ── 问题18: 异常吞没 ──► 空 patch 产出
            │
            ▼
    Merge Executor
    ├─ 问题4: 丢弃所有 patch ──► merge 结果空
    └─ 问题28: 终止延迟 ──► 多余合并轮次
            │
            ▼
    Toxicity Test
    ├─ 问题2: 误判为 toxic ──► patch 全拒绝
    ├─ 问题3: 静默放行 ──► patch 全放行
    └─ 问题5: 崩溃 ──► ToxicityReport 无法生成
            │
            ▼
    Apply Patch ── 问题24: None 崩溃 ──► 应用失败
            │
            ▼
    Few-shot Phase ── 问题6: artifact 空 ──► 过程数据丢失
            │
            ▼
    Resume ── 问题1: 统计丢失 ──► run_summary 错误
```

---

## 七、修复优先级建议

### P0 - 立即修复（影响核心功能正确性）

| 编号 | 问题 | 修复方案 |
|------|------|----------|
| 2 | extraction 模式 spec None 保护 | 增加 `if spec is None: return False` |
| 4 | merge provenance 全丢弃 | `not mapped_any` 分支仅跳过当前 merged_dict |
| 5 | 测毒循环无异常处理 | 增加 try/except 包裹 `_test_single_sample` |
| 3 | executor None 静默放行 | 改为 `raise ValueError` 或保守判 break |
| 31 | None 值迭代崩溃 | 使用 `or []` 兜底 |

### P1 - 近期修复（影响数据完整性和 prompt 质量）

| 编号 | 问题 | 修复方案 |
|------|------|----------|
| 6 | fewshot artifact 空 | 增加对应字段或调整保存逻辑 |
| 7 | 代码块丢失 | 修复 MarkdownParser 代码块处理 |
| 10 | extraction regression 检查 | 增加 `patched_accuracy >= base_accuracy` 检查 |
| 9 | ema_alpha 失效 | 使用 `self.ema_alpha` 替代硬编码 0.3 |
| 1 | resume 统计丢失 | 加载历史 run_summary 并累加新迭代统计 |

### P2 - 后续修复（影响可观测性和边界场景）

| 范围 | 问题编号 |
|------|----------|
| 异常处理/日志 | 17, 18, 26, 34 |
| 状态管理 | 11, 12, 13, 14, 23 |
| 接口一致性 | 27 |
| 算法正确性 | 28, 29, 30 |
| 条件分支/边界 | 15, 16, 19, 20, 21, 22, 24, 25, 32, 35-39 |

---

## 八、附录

### 8.1 审查方法

本次审查采用以下方法：
1. **逐文件完整阅读**：使用 `Read` 工具完整读取每个文件的全部内容
2. **交叉验证**：对跨模块调用链进行追踪，验证 API 假设的正确性
3. **边界条件分析**：针对空值、None、异常输入等边界场景进行推演
4. **数据流追踪**：从输入到输出追踪关键数据的流转路径
5. **并发安全审查**：对 `ThreadPoolExecutor` 使用场景进行线程安全分析

### 8.2 验证方式

- 代码证据：所有问题均附有具体行号，可直接定位
- 逻辑推演：对复杂问题提供具体反例验证
- 跨模块交叉：验证调用方与被调用方的接口契约一致性

---

*报告生成：2026-06-29*
