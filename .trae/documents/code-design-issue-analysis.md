# 代码与设计问题分析报告

## 摘要

通过对 mmap_optimizer 全代码库的深入分析，共发现 **42 个问题**，其中严重 8 个、中等 17 个、低 17 个。问题主要集中在三类：(1) 字段/枚举/模块定义了但从未使用（死代码）；(2) 设计意图与代码实现不一致（名实不符）；(3) 参数传递链断裂导致功能名义启用但实际不工作。

---

## 一、严重问题（影响功能正确性）

### S1. 历史回归检测功能完全失效

**位置**：
- `testing/patch_tester.py:78-84` — `summarize_patch_test` 接受 `historically_fixed_sample_ids` 参数并填充 `historical_fixed_regression_count`，但该字段**不参与接受决策**
- `testing/suite_builder.py` — `build_individual_suite` 和 `build_bundle_suite` **不接受** `historically_fixed_sample_ids` 参数，历史修复样本不会被显式纳入测试套件
- `orchestration/round_runner.py:258` — 收集了 `historically_fixed_ids` 但只传给 `summarize_patch_test`，未传给 `suite_builder`

**设计意图**：检测新 patch 是否导致之前已修复的样本重新出错（跨 round 回归）。

**实际行为**：`historical_fixed_regression_count` 几乎永远为 0（历史样本只有恰好通过 correct/wrong 列表进入 suite 才会被测试到），即使非 0 也不影响 patch 接受决策。`config.historical_regression_check_enabled=True` 名义启用但实际不工作。

**对比 Canary 保护**：Canary 有完整的"选择→纳入 suite→检测→拒绝"链路，历史回归只有"收集→传递→填充"，缺少"纳入 suite"和"拒绝"两环。

### S2. `analysis/evolution.py` 的 `SCHEMA_IMMUTABILITY_VIOLATION` 匹配永远失败

**位置**：`analysis/evolution.py:139`

```python
p.rejection_reason == "SCHEMA_IMMUTABILITY_VIOLATION"
```

**问题**：`patch/validator.py:68` 实际返回的是 `f"SCHEMA_IMMUTABILITY_VIOLATION: forbidden keyword {word!r} found in patch_text"`（带后缀）。`==` 精确匹配永远为 `False`，`schema_violation_patch` 触发条件永不激活。

**修复**：改为 `p.rejection_reason and p.rejection_reason.startswith("SCHEMA_IMMUTABILITY_VIOLATION")`。

### S3. `verify_ssl` 配置被静默忽略

**位置**：`model/factory.py:20`

```python
return OpenAICompatibleClient(base_url=config.base_url, api_key=api_key, model=config.model)
```

**问题**：`ModelConfig.verify_ssl` 字段被定义和解析，但 `build_model_client` 没有传递给 `OpenAICompatibleClient`。用户配置 `verify_ssl: false` 会被静默忽略，SSL 验证始终为 `True`。

**修复**：`OpenAICompatibleClient(base_url=config.base_url, api_key=api_key, model=config.model, verify_ssl=config.verify_ssl)`。

### S4. `_load_existing_checkpoint` 签名与实现矛盾

**位置**：`orchestration/optimizer_loop.py:157-161`

```python
def _load_existing_checkpoint(self) -> OptimizerCheckpoint | None:
    checkpoint_path = self.store.root / "checkpoint.json"
    if not Path(checkpoint_path).exists():
        raise FileNotFoundError(...)  # 签名说返回 None，实际抛异常
    return OptimizerCheckpoint.load(checkpoint_path)
```

**问题**：返回类型标注为 `OptimizerCheckpoint | None`，调用方用 `if existing is not None:` 检查，但文件不存在时抛 `FileNotFoundError` 而非返回 None。resume 模式下首次运行（无 checkpoint.json）会直接崩溃。

### S5. Resume 逻辑只恢复 round_index，不恢复状态

**位置**：`orchestration/optimizer_loop.py:67-70`

**问题**：`_load_existing_checkpoint` 加载了 checkpoint，但只使用 `round_index` 计算 `effective_start`。checkpoint 中保存的 `active_prompts` 和 `sample_states` 完全没有被用来恢复 `OptimizerState`。真正的状态恢复依赖外部传入的 `state`，checkpoint 实际只起到"记录已完成到第几轮"的作用。

### S6. `historical_fixed` 和 `toxic_trigger` 字段从未被赋值

**位置**：`dataset/sample.py:46-47`

**问题**：`SampleState` 定义了 `historical_fixed: bool = False` 和 `toxic_trigger: bool = False`，但全代码库中**从未被赋值**。`sampling/risk_signals.py:121,139-147` 读取这两个字段做风险评分，但它们永远是 `False`，相关风险评分组件永远不生效。

同时 `_collect_historically_fixed_sample_ids` 方法名暗示应使用 `historical_fixed` 字段，实际用的是 `consecutive_correct_count > 0`，名实不符。

### S7. `compression/engine.py` 和 `compression/semantic.py` 的 dict content bug

**位置**：
- `compression/engine.py:369-374` — `_run_analysis_behavior_suite` 中 user message content 直接传 dict
- `compression/semantic.py:50,72` — 同样传 dict

**问题**：`analysis/runner.py:70-79` 将 content 序列化为 `json.dumps(..., ensure_ascii=False)` 字符串，但 compression 模块直接传 dict。`OpenAICompatibleClient` 将 messages 直接传给 API，OpenAI API 要求 content 为 string，传 dict 会导致 API 400 错误。

### S8. `fewshot/engine.py:110` 的 KeyError 风险

**位置**：`fewshot/engine.py:110`

```python
example = self._generate_example(candidate, source_sample, ground_truths[source_sample.ground_truth_id], contract)
```

**问题**：直接用 `ground_truths[source_sample.ground_truth_id]` 访问字典，未做存在性检查。若 ground truth 未加载，抛出 `KeyError` 导致整个 fewshot 优化崩溃。对比行 104 的 `source_sample = sample_by_id.get(candidate.sample_id)` + None 检查，应做同样防护。

---

## 二、中等问题（死代码/设计不一致）

### M1. `merge_ranking.py` 整个模块未被集成（约 380 行死代码）

**位置**：`patch/merge_ranking.py`

**问题**：`build_merge_candidates_from_patches`、`rank_patch_merge_candidates`、`select_top_merge_candidates`、`PatchMergeCandidate` 仅在模块内部互相调用，没有任何外部模块导入。实际合并流程使用 `TreeReducePatchMerger`，完全不经过 `merge_ranking.py`。`side_effect_risk` 字段虽然在模块内逻辑正确，但整个模块是孤立的。

### M2. `PatchTestResult` 有 4 个死/半死字段

**位置**：`testing/patch_tester.py:18-36`

| 字段 | 状态 |
|------|------|
| `format_error_count` | 从未填充，恒为 0 |
| `unchanged_wrong_sample_ids` | 仅填充，无下游读取 |
| `unchanged_correct_sample_ids` | 仅填充，无下游读取 |
| `historical_fixed_regression_count` | 填充但不参与决策（见 S1） |

### M3. `PatchStatus` 枚举定义但从未使用

**位置**：`core/enums.py:20-29`

**问题**：定义了完整的 `PatchStatus` 枚举（DRAFT、CANDIDATE、MERGED、TESTING、ACCEPTED、REJECTED、QUARANTINED、SUPERSEDED、ROLLED_BACK），但全代码库使用裸字符串字面量。`TESTING`、`QUARANTINED`、`ROLLED_BACK` 三个状态从未被设置。

### M4. `RoundStage` 有 8 个枚举值从未使用

**位置**：`orchestration/records.py:8-24`

未使用的阶段：`OPTIMIZATION_BATCH_SELECT`、`DYNAMIC_VALIDATION`、`PATCH_GENERATION`、`PATCH_TREE_REDUCE`、`PATCH_RANKING`、`ANALYSIS_EVOLUTION`、`METRICS`、`FAILED`。

`current_stage` 无法准确反映 round 的真实执行进度，crash recovery 时无法精确定位崩溃点。

### M5. Intermediate 文件"写了但从不读"

**位置**：`orchestration/round_runner.py:622-635`

**问题**：`_save_intermediate` 在 7 个 checkpoint 点写入 intermediate JSON 文件，但 `OptimizerLoop` 的 resume 逻辑完全不读取这些文件。`_cleanup_intermediate` 只在成功完成时调用，崩溃后 intermediate 文件残留但无恢复逻辑消费它们。

### M6. Checkpoint 的 `sample_states` 保存不完整

**位置**：`orchestration/optimizer_loop.py:138-146`

**问题**：只保存 `sample_id`、`difficulty_ema`、`fragility_score`、`last_selected_round` 四个字段，丢失了 `consecutive_correct_count`（影响 canary 选择）、`consecutive_wrong_count`、`selected_count_recent_window`、`historical_fixed`、`toxic_trigger`。即使 resume 逻辑将来要恢复 sample_states，canary 保护和历史回归检查在 resume 后也会失效。

### M7. `fewshot_pool_path` 永远硬编码为 None

**位置**：`orchestration/optimizer_loop.py:97`

```python
self._save_checkpoint(round_index, state, metrics, fewshot_pool_path=None)
```

**问题**：`round_runner.py:434-449` 会读写 `fewshot_candidate_pool.json`，但路径从未传入 checkpoint。resume 后无法定位 fewshot pool 文件。

### M8. `PromptVersion.from_dict` 中 `_extra` 被直接覆盖

**位置**：`prompt/version.py:49-50`

```python
obj = cls(**fields)       # 如果 data 含 _extra，obj._extra 已被正确设置
if extra:
    obj._extra = extra    # 直接覆盖！原有的 _extra 内容丢失
```

**修复**：`obj._extra = {**obj._extra, **extra}`。

### M9. `tree_reduce.py` 合并后 `operation_mode` 硬编码为 `"append"`

**位置**：`patch/tree_reduce.py:136`

**问题**：合并后的 patch 强制使用 `append` 模式，丢弃了原始 patches 的 `operation_mode`（可能是 `replace_in_section`、`insert_after` 等）。文本级精确 patch 合并后行为异变。

### M10. `analysis/runner.py` 的 `source_run is None` 检查时机错误

**位置**：`analysis/runner.py:106-112`

**问题**：`source_run is None` 检查发生在模型调用（行 81）和解析（行 92）之后。已消耗 API 调用成本，已创建 `analysis_run` 对象，但 `continue` 丢弃了该 run 记录，不会出现在返回结果中，无法审计。

### M11. 空 `primary_answer_fields` 处理不一致

**位置**：
- `evaluation/evaluator.py:77,154` — 回退到魔法字符串 `"result"`
- `fewshot/engine.py:226` — `all([])` 返回 `True`，`primary_matches` 恒为 True

**问题**：三处对空列表的语义不一致，可能导致 fewshot 优化生成的 example 与 evaluator 的判断逻辑脱节。

### M12. `validation_policy` 中两个字段未被使用

**位置**：`prompt/contract.py:18-22`

- `missing_required_fields_allowed` — `schema_validator.py` 不参考此策略
- `require_schema_valid_for_correct` — `evaluator.py:158` 硬编码"schema 无效则不正确"

### M13. `compression/engine.py:155` 的行数判断与 token budget 矛盾

**位置**：`compression/engine.py:155`

**问题**：当 `token_exceeded` 为 True 但 `line_exceeded` 为 False 时，仍要求 `after_lines < before_lines` 才接受压缩。"行数不变但 token 减少"的压缩会被拒绝。

### M14. `compress_analysis_if_needed` 返回空 evaluations

**位置**：`compression/engine.py:277,280`

**问题**：返回签名声明 `list[EvaluationRecord]`，但实际总返回空列表。与 `compress_if_needed` 返回实际 evaluations 不一致。

### M15. `RunStateStore.load` 从未被调用；RunState 3 个字段从未赋值

**位置**：`orchestration/run_state.py:14-17, 28-33`

**问题**：`run_state.json` 被反复写入但从不读取。`active_extraction_prompt_id`、`active_analysis_prompt_id`、`metadata` 三个字段永远是默认值。

### M16. `OptimizerState.analysis_output_schema_contract` 从未使用

**位置**：`orchestration/round_runner.py:53`

**问题**：在 `run_round` 中从未被引用，是未使用字段。

### M17. `historical_regression_check_enabled` 配置节归属错误

**位置**：`core/config.py:342`

**问题**：`historical_regression_check_enabled` 是独立功能，但配置键 `historical_check_enabled` 嵌套在 `post_apply_regression` 节下解析，语义混乱。

---

## 三、低等问题（代码质量）

### L1. `_post_apply_regression_check` 的 runs/evaluations 未持久化

**位置**：`orchestration/round_runner.py:675-683`

回归检查的 LLM 调用记录完全丢失，无法审计。对比 extraction/dval/patch test runs 都被写入 JSONL。

### L2. `_select_safe_bundle` 用 `not in` 比较 Patch 对象而非 id

**位置**：`orchestration/round_runner.py:314`

Patch 是 dataclass，`in` 使用 `__eq__`。两个字段值相同的 Patch 会被误判为相等。应使用 `id` 比较。

### L3. `Transition.CHANGED_BUT_STILL_CORRECT` 枚举值从未返回

**位置**：`core/enums.py:56` + `testing/transition.py`

`classify_transition` 只返回 4 个值，第 5 个枚举值是死代码。

### L4. `PromptVersionType.ANALYSIS_SHADOW_PROMOTION` 和 `MANUAL` 从未使用

**位置**：`core/enums.py:15,17`

### L5. 函数内 `import random`

**位置**：`orchestration/round_runner.py:660`

应放在文件顶部。

### L6. `FAILED` stage 从未设置

**位置**：`orchestration/round_runner.py`（无 try/except）

崩溃的 round 会停留在最后一个成功的 stage，无法区分"在此阶段崩溃"和"此阶段已完成"。

### L7. `metrics_summary` 中 `round_id` 实际存的是 int 序号

**位置**：`orchestration/optimizer_loop.py:149`

字段名误导，`round_id` 应为字符串如 "round_000001"，实际存的是整数如 1。

### L8. `tree_reduce.py` 单 patch 幸存者被标记为 `"merged"`

**位置**：`patch/tree_reduce.py:100-103`

单 patch 通过过滤无实际合并发生，却被标记为 `"merged"`，混淆审计。

### L9. `tree_reduce.py` 合并后 `intent_name` 被覆盖

**位置**：`patch/tree_reduce.py:137`

丢失原始 intent 名称，影响下游追踪。

### L10. `semantic.py:41` 索引越界 fallback 不合理

**位置**：`patch/semantic.py:41`

LLM 返回的 patch 数量超过输入时，多出项全部使用 `patches[-1]` 作为 fallback，可能产生错误归因。

### L11. `semantic.py:96` None 值污染

**位置**：`patch/semantic.py:96`

`data.get("semantic_template_id")` 返回 None 时，`extra` 字典会包含 `"semantic_template_id": None`。

### L12. `fewshot/engine.py:235` schema_valid 与 reasoning_text 耦合

**位置**：`fewshot/engine.py:235`

`schema_valid=schema_result.valid and bool(reasoning_text.strip())` 将 reasoning 非空与 schema 有效性耦合。

### L13. `fewshot/engine.py:326` ValueError 风险

**位置**：`fewshot/engine.py:326`

`int(line.split(":", 1)[1])` 未处理非数字输入。

### L14. `analysis/runner.py:130-131` 冗余字段赋值

`invalid_patch_candidate_count` 和 `invalid_patch_count` 赋了相同的值。

### L15. `compression/semantic.py:59-61` 无效重试

相同参数重试，对确定性模型无意义。

### L16. `suite_builder.py` composition 字典在截断时计数不准

**位置**：`testing/suite_builder.py:14,20`

`sample_ids` 被 `[:max_samples]` 截断，但 `composition` 使用原始长度。

### L17. `evaluator.py:118` `primary_answer_correct` 命名误导

在 `evaluate_without_ground_truth` 中实际表示"首轮预测等于多数票"，而非"答案正确"。

---

## 四、问题统计

| 严重度 | 数量 | 影响 |
|--------|------|------|
| 严重 | 8 | 功能失效、崩溃、数据丢失 |
| 中等 | 17 | 死代码、设计不一致、功能不完整 |
| 低 | 17 | 代码质量、命名、审计 |
| **总计** | **42** | |

## 五、按模块分布

| 模块 | 严重 | 中等 | 低 | 小计 |
|------|------|------|-----|------|
| orchestration | 2 | 6 | 4 | 12 |
| testing/patch | 1 | 2 | 2 | 5 |
| patch | 1 | 2 | 3 | 6 |
| core/config | 1 | 1 | 1 | 3 |
| core/enums | 0 | 2 | 1 | 3 |
| prompt | 0 | 2 | 0 | 2 |
| analysis | 1 | 1 | 1 | 3 |
| evaluation | 0 | 2 | 1 | 3 |
| fewshot | 1 | 1 | 2 | 4 |
| compression | 1 | 2 | 1 | 4 |
| dataset | 1 | 0 | 0 | 1 |

## 六、建议修复优先级

### P0（立即修复 - 影响功能正确性）
1. S1: 历史回归检测 — suite_builder 接受 historical_fixed_sample_ids + summarize 拒绝逻辑
2. S2: evolution.py 的 `startswith` 修复
3. S3: factory.py 传递 verify_ssl
4. S4: `_load_existing_checkpoint` 返回 None 而非抛异常
5. S7: compression 模块 dict content → json.dumps
6. S8: fewshot/engine.py ground_truths.get() + None 检查

### P1（尽快修复 - 死代码清理/设计一致性）
7. S6: 赋值 `historical_fixed` 和 `toxic_trigger` 字段
8. M8: PromptVersion `_extra` 覆盖修复
9. M9: tree_reduce operation_mode 保留
10. M10: analysis/runner.py 检查时机前移
11. M11: 统一空 primary_answer_fields 处理
12. M12: 启用或移除 validation_policy 未使用字段

### P2（后续优化 - 代码质量）
13. M1-M7: 死代码清理和 checkpoint 完整性
14. L1-L17: 各类小问题

## 七、验证步骤

1. 每个严重问题修复后运行相关单元测试
2. 死代码清理后确认无导入断裂
3. 配置项变更后验证 `optimizer_config_from_mapping` 解析正确
4. 全量测试：`python -m pytest tests/ -x -q`
