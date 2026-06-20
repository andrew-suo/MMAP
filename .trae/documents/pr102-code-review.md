# PR #102 代码审查报告：7 步提取提示优化管线

## 审查范围

| 文件 | 行数 | 说明 |
|------|------|------|
| `mmap_optimizer/orchestration/round_runner.py` | 1737 | 7 步管线主逻辑、双客户端路由、指标收集 |
| `mmap_optimizer/compression/engine.py` | ~450 | 提取/分析提示压缩引擎 |
| `mmap_optimizer/fewshot/engine.py` | ~360 | Few-shot 槽位管理引擎 |
| `mmap_optimizer/fewshot/report.py` | ~40 | Few-shot 优化报告数据结构 |
| `mmap_optimizer/analysis/evolution.py` | ~230 | 分析提示 shadow 演进引擎 |
| `mmap_optimizer/analysis/blind_evaluation.py` | ~420 | 盲评运行器（3-vote majority） |
| `mmap_optimizer/analysis/runner.py` | ~370 | 分析运行器（patch 候选生成） |

---

## 严重问题（共 18 项，需优先修复）

### S1. 失败重试会抹掉前序成功迭代的已接受补丁
- **文件**: `round_runner.py` 第 290-337 行
- **问题**: 当某次迭代成功后，下一次迭代失败（非 `empty_final_patch_set` 原因）时，代码执行 `state.active_extraction_prompt = initial_extraction_prompt` 和 `round_record.accepted_patch_ids = []`，**回滚到最初 prompt 并清空所有前序成功迭代的累积补丁**。`already_had_success` 守卫仅捕获 `empty_final_patch_set` 一种拒绝原因。
- **影响**: 多迭代场景下优化成果被意外清空
- **修复方向**: 扩大 `already_had_success` 守卫范围，或改为回滚到上一次成功状态而非初始状态

### S2. `patched_accuracy` 反映合并全量补丁而非最终接受的安全子集
- **文件**: `round_runner.py` 第 1076-1078 行
- **问题**: `patched_acc` 使用 Step 6 的 `patched_evals`（全量 merged_patches 一起应用），但实际接受的是 Step 7 贪心安全子集筛选后的 `final_patches`（可能更小）
- **影响**: 早退判断 `patched_accuracy == 1.0` 可能因 toxic 补丁存在而无法触发；上报指标与实际应用补丁集不匹配
- **修复方向**: 使用 Step 7 安全子集的评估结果计算 `patched_accuracy`

### S3. 贪心安全子集使用 `initial_extraction_prompt` 而非当前 active prompt
- **文件**: `round_runner.py` 第 907 行
- **问题**: 多迭代场景中，第二次迭代的 Step 7 贪心筛选从**原始 prompt** 出发测试补丁毒性，但 Step 8 最终 apply 是应用到**当前已修改的** `state.active_extraction_prompt`
- **影响**: 毒性判断基于错误 prompt，可能导致误判
- **修复方向**: 使用 `state.active_extraction_prompt` 作为贪心筛选的基线

### S4. `compression_triggered` 永远为 True
- **文件**: `round_runner.py` 第 511-513 行
- **问题**: `compression_reports` 总是至少包含一个元素（即使压缩未触发），`if compression_reports:` 恒为 True
- **修复方向**: `metrics.compression_triggered = any(getattr(r, "triggered", False) for r in compression_reports)`

### S5. `patch_test_results.jsonl` 中 `base_evals` 与 `patched_evals` 相同
- **文件**: `round_runner.py` 第 557-564 行
- **问题**: 传入相同的 `extraction_result.evaluations` 作为基线和补丁后评估，导致所有样本被分类为 `unchanged_*`，永远不会出现 `fixed` 或 `broken`。随后又用 patch 状态覆盖结果，使 `summarize_patch_test` 的计算完全被丢弃
- **修复方向**: 将 Step 6 的 `patched_evals` 暴露在 `ExtractionOptimizationResult` 中并传入

### S6. 仅保存最后一次成功迭代的 artifacts
- **文件**: `round_runner.py` 第 380-384 行
- **问题**: `extraction_result` 被重赋值为 `_last_successful_extraction` 后，保存的 runs/analyses/patches 均只来自最后一次成功迭代，其他迭代数据全部丢失
- **影响**: 无法审计完整优化轨迹
- **修复方向**: 累积保存所有迭代数据，或至少保存失败迭代的摘要

### S7. 分析补丁验证使用了错误的 prompt IR
- **文件**: `round_runner.py` 第 1252 行
- **问题**: 分析 prompt 的补丁验证却针对**提取 prompt 的 IR**（`state.active_extraction_prompt.prompt_ir`）
- **修复方向**: 改为 `state.active_analysis_prompt.prompt_ir`

### S8. `extraction_output` 传入 run ID 而非实际内容
- **文件**: `round_runner.py` 第 1205、1238 行
- **问题**: `extraction_output=blind_rec.extraction_run_id` 传入的是运行 ID 字符串，而 `run_single_analysis` 会将其序列化为 user 消息作为"提取输出"供分析 prompt 判断
- **影响**: 分析 prompt 收到 run ID 而非实际提取结果
- **修复方向**: 传入实际的提取输出内容

### S9. 分析压缩无输出等价性校验（`base_runs=[]`）
- **文件**: `compression/engine.py` 第 230-234 行 + 第 414-426 行
- **问题**: 调用方始终传入 `base_runs=[]`，触发回退到 `error_evaluations`，但 `_analysis_behavior_failure` 在无基线时仅检查候选能否解析+schema 合法，**完全不校验输出等价性**
- **影响**: 压缩可能把分析结论从"合格"改成"不合格"仍被接受
- **修复方向**: 无基线时使用候选自身的前后对比，或要求调用方传入基线 runs

### S10. 基线 parse 失败时修复型候选被误拒
- **文件**: `compression/engine.py` 第 418-422 行
- **问题**: 当 `baseline.success=False`（`parsed_output=None`）而候选 `success=True`（`parsed_output={...}`）时，`None != {...}` 返回 `ANALYSIS_OUTPUT_CHANGED`，即候选修复了基线的 parse 错误反而被拒绝
- **修复方向**: 基线失败时不应将候选的成功视为"行为变更"

### S11. 浅拷贝导致 `best_report.rejected_candidates` 被污染
- **文件**: `fewshot/engine.py` 第 149 行
- **问题**: `replace(report)` 是浅拷贝，`rejected_candidates` list 与原对象共享引用。后续拒绝记录会追加到同一 list，污染 `best_report`
- **修复方向**: `replace(report, rejected_candidates=list(report.rejected_candidates))`

### S12. `_regressions` 把基线已有错误计为违规，阻塞所有候选
- **文件**: `fewshot/engine.py` 第 405 行
- **问题**: `if candidate.overall_status in {"parse_error", "schema_error"} ...` 不与基线对比。若基线某样本本身就是 parse_error，候选维持同样错误仍被计入 `schema_violations`
- **影响**: 只要 baseline 中存在任何 schema/parse 错误样本，几乎所有候选都会被拒
- **修复方向**: `if (候选违规) and not (基线同样违规)`

### S13. `FewShotSetVersion.slots` 只含 1 个槽位
- **文件**: `fewshot/engine.py` 第 302-303 行
- **问题**: 无论 ADD_SLOT 还是 REPLACE_SLOT，`slots` 列表只包含当前操作的那一个槽位，丢失其余槽位信息。`slot_count` 字段与 `slots` 列表长度不一致
- **修复方向**: `slots` 应描述整个 few-shot 集合的槽位布局

### S14. 缺 `rejected_candidate_count` 字段，指标恒为 0
- **文件**: `fewshot/report.py` + `round_runner.py` 第 537-538 行
- **问题**: `FewShotOptimizationReport` 没有 `rejected_candidate_count` 字段，`getattr(r, "rejected_candidate_count", 0)` 恒返回 0
- **修复方向**: 添加字段或改用 `len(r.rejected_candidates)`

### S15. `version_type="patch_application"` 是无效枚举值
- **文件**: `analysis/evolution.py` 第 112-114 行
- **问题**: `PromptVersionType` 枚举不存在 `patch_application`，应使用 `ANALYSIS_SHADOW_PROMOTION`
- **影响**: 下游 `version_type == PromptVersionType.XXX` 的枚举比较无法匹配
- **修复方向**: 改为 `PromptVersionType.ANALYSIS_SHADOW_PROMOTION`

### S16. Shadow 评估是"橡皮图章"，候选永远被接受
- **文件**: `analysis/evolution.py` 第 117-139 行 + 第 210-228 行
- **问题**: `_candidate_metrics` 将候选指标**硬编码为完美值**（`schema_violation_patch_rate=0.0`、`toxic_risk_recall=1.0` 等），`hard_gate_passed` 永远为 True，`improved` 永远非空，因此 `accepted` **永远为 True**
- **影响**: 只要有 valid patches，候选必然被接受，不存在真正的质量门控
- **修复方向**: 实际运行候选 prompt 验证，或明确文档标注为"自动接受"模式

### S17. `BlindEvaluationRunner` 是死代码，从未被调用
- **文件**: `analysis/blind_evaluation.py` 整个文件
- **问题**: `round_runner.py` 内联构建了 blind records（使用简化的 `_BlindRecord`），而非调用 `BlindEvaluationRunner`。`blind_evaluation.py` 中所有复杂逻辑（3-vote majority、`is_correct` 回退、reflection 生成）**在生产中从未被执行**
- **修复方向**: 接入 `BlindEvaluationRunner` 或删除死代码

### S18. `judgement.get("is_correct")` 在 judgement 非字典时崩溃
- **文件**: `analysis/runner.py` 第 114-124 行
- **问题**: 未检查 `parsed["judgement"]` 本身是否为 dict。若模型输出 `{"judgement": "correct"}`，则 `judgement = "correct"`，`judgement.get("is_correct")` 抛 `AttributeError`
- **修复方向**: 添加 `isinstance(judgement, dict)` 保护

---

## 中等问题（共 20 项）

### M1. `_run_analysis_evolution` 使用了最后一次（可能失败的）迭代结果
- **文件**: `round_runner.py` 第 348-353 行
- **问题**: 调用在 `extraction_result` 重赋值为 `_last_successful_extraction` 之前，分析进化引擎收到的是最后一次迭代（可能失败）的结果

### M2. `no_analysis_errors` 早退路径中 `base_accuracy` 与 `base_correct_count` 矛盾
- **文件**: `round_runner.py` 第 1178-1184 行
- **问题**: `base_accuracy=1.0` 但 `base_correct_count=0`，若 accuracy 为 100%，correct_count 应等于 total_count

### M3. 确定性失败仍消耗重试预算
- **文件**: `round_runner.py` 第 298-311 行
- **问题**: 当所有补丁被判定为 INEFFECTIVE/TOXIC 时（确定性结果），仍消耗 `max_restart_attempts` 重试，浪费 LLM 调用

### M4. `valid_patch_candidate_rate` 计算的是接受率而非有效率
- **文件**: `round_runner.py` 第 485-496 行
- **问题**: 回退分支计算 `accepted / total`，语义与字段名"有效补丁候选率"不符

### M5. 压缩/fewshot 接受后 prompt 未保存
- **文件**: `round_runner.py` 第 585-586 行
- **问题**: 仅当有接受补丁时才保存提取 prompt；若本轮无补丁但压缩/fewshot 修改了 prompt，则不会持久化。分析 prompt 从未在此处保存

### M6. 分析压缩使用提取评估找 wrong samples
- **文件**: `round_runner.py` 第 1461 行
- **问题**: `base_evaluations` 是提取评估，但用于分析压缩引擎判断哪些样本需要分析 prompt 改进，语义错配

### M7. token 超限时无 token 缩减校验
- **文件**: `compression/engine.py` 第 156、274 行
- **问题**: 仅校验 `line_exceeded` 的行数缩减，当触发条件是 `token_exceeded=True` 而 `line_exceeded=False` 时，候选即使 token 没减少也会被接受

### M8. 分析压缩不覆盖正确样本
- **文件**: `compression/engine.py` + `round_runner.py` 第 1461 行
- **问题**: `behavior_evaluations` 只含错误样本，压缩可能破坏正确样本的分析行为但不会被检测到

### M9. `_compress_content` strip 破坏缩进语义
- **文件**: `compression/engine.py` 第 428-437 行
- **问题**: `line.strip()` 去掉行首缩进，对 Markdown 嵌套列表、代码块、YAML 风格内容是语义破坏

### M10. 替换槽位策略固定选最小 index
- **文件**: `fewshot/engine.py` 第 319-331 行
- **问题**: 始终替换第一个槽位，无法淘汰低价值示例，多轮优化中同一槽位被反复替换

### M11. 解析失败时 `max_slots` 约束被绕过
- **文件**: `fewshot/engine.py` 第 329-330 行 + 第 278 行
- **问题**: 槽位 `slot_index` 异常时 `_replacement_slot` 返回 None，走 ADD_SLOT 分支，导致槽位数超过 `max_slots`

### M12. 默认允许零提升候选
- **文件**: `fewshot/engine.py` 第 131、143 行
- **问题**: `min_accuracy_delta=0.0` 允许 `delta == 0.0` 的候选被接受为 `best_safe`，无任何收益

### M13. 槽位解析对畸形行不健壮
- **文件**: `fewshot/engine.py` 第 344 行
- **问题**: `int(line.split(":", 1)[1])` 对 `FEW_SHOT_SLOT:abc` 或 `FEW_SHOT_SLOT:` 会抛未捕获的 `ValueError`

### M14. ADD_SLOT `slot_index` 可能碰撞
- **文件**: `fewshot/engine.py` 第 279 行
- **问题**: `slot_index = len(slots) + 1` 假设索引连续，若存在空洞则碰撞

### M15. 未传 `round_id` 给 `PatchApplier`，丢失溯源
- **文件**: `analysis/evolution.py` 第 110-114 行
- **问题**: 生成的候选 `PromptVersion` 的 `created_by_round_id` 为 None

### M16. `run_single_analysis` 缺少 `is_correct` 回退，与 `blind_evaluation.py` 不一致
- **文件**: `analysis/runner.py` 第 230-236 行
- **问题**: 分析只输出 `is_correct` 而无 `primary_label` 时，`matches_truth` 恒为 False。`blind_evaluation.py` 有回退逻辑但 `run_single_analysis` 没有

### M17. `generate_analysis_patch` 与 `analyze_errors` 的 patch ID 可能碰撞
- **文件**: `analysis/runner.py` 第 159、364 行
- **问题**: 两个方法使用相同的 patch ID 格式 `patch_{round_id}_{sample_id}_{index:02d}`

### M18. `extraction_run_id` 和 `evaluation_record_id` 语义错配
- **文件**: `analysis/runner.py` 第 344-345 行
- **问题**: `extraction_run_id` 被设为 analysis run 的 ID，`evaluation_record_id` 被设为空字符串

### M19. `possible_side_effects` 被填入风险级别字符串
- **文件**: `analysis/runner.py` 第 174 行
- **问题**: `risk` 是 `"high"/"medium"/"low"` 级别，被放入 `possible_side_effects` 列表，语义错误

### M20. `analysis_evolution_report_id` 的 if/else 两分支完全相同
- **文件**: `round_runner.py` 第 1417-1421 行
- **问题**: 两个分支都执行 `round_record.analysis_evolution_report_id = report.id`，if/else 多余

---

## 代码质量问题（共 12 项）

| 编号 | 文件 | 问题 |
|------|------|------|
| Q1 | round_runner.py:278 | 浮点数等值比较 `== 1.0`，建议 `>= 1.0` |
| Q2 | round_runner.py:441-443 | `accepted_count` 与 `rejected_count` 设置条件不对称 |
| Q3 | round_runner.py:597-599 | 死代码：`if hasattr(...) ... pass` |
| Q4 | round_runner.py:1497-1499 | fewshot pool 读写路径风格不一致（绝对 vs 相对） |
| Q5 | round_runner.py:1433 | 提取压缩使用 `analysis_json_repair_enabled` 配置（疑似复制粘贴错误） |
| Q6 | round_runner.py:1521-1584 | `_select_safe_bundle` 方法存在但未被调用（遗留代码） |
| Q7 | round_runner.py:1198,1229,1303 | `AnalysisRunner` 在循环内重复实例化 |
| Q8 | compression/engine.py:164,282 | `semantic_check_passed` 对确定性压缩无条件置 True |
| Q9 | fewshot/engine.py:179 | `bundle_accuracy_delta` 被用作单候选 `accuracy_delta` |
| Q10 | evolution.py:82-92 | `generated_patch_ids` 命名歧义（只含通过验证的 patch） |
| Q11 | blind_evaluation.py:222 | `three_outputs` 依赖 `locals()` 检查，脆弱 |
| Q12 | runner.py:363 | `generate_analysis_patch` 原地修改 candidate 字典 |

---

## 修复优先级建议

### P0 - 立即修复（影响正确性，可能导致管线产出错误结果）
1. **S1**: 失败重试抹掉成功迭代补丁
2. **S2 + S3**: patched_accuracy 错配 + 贪心用错 prompt
3. **S9 + S10**: 分析压缩无等价性校验 + 修复型候选被误拒
4. **S12**: fewshot `_regressions` 误判基线错误，阻塞所有候选
5. **S15**: 无效 `version_type` 枚举值
6. **S18**: judgement 非字典时崩溃

### P1 - 尽快修复（影响指标准确性和审计能力）
7. **S4**: compression_triggered 恒真
8. **S5**: patch_test_results 基线=补丁
9. **S6**: artifact 丢失
10. **S7 + S8**: 分析补丁验证用错 IR + extraction_output 传 run ID
11. **S11**: fewshot 浅拷贝污染
12. **S14**: 缺 rejected_candidate_count 字段
13. **S16**: shadow 评估形同虚设
14. **S17**: BlindEvaluationRunner 死代码

### P2 - 后续改进（代码质量和健壮性）
15. **S13**: FewShotSetVersion.slots 不完整
16. **M1-M20**: 所有中等问题
17. **Q1-Q12**: 所有代码质量问题

---

## 验证步骤

1. 修复后运行 `python -m pytest tests/test_patch_and_round.py -v` 确认 19 个测试仍全部通过
2. 针对每个 P0 修复项编写新的边界测试用例
3. 运行完整测试套件 `python -m pytest tests/ -v` 确认无回归
4. 对多迭代场景进行集成测试（当前测试多为单轮）
