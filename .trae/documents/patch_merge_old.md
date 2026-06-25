Parallel Patch Merge 算法文档

1. 概述
   Parallel Patch Merge（并行补丁合并）是一种分层树形递归归约（Hierarchical Tree-Reduce）算法，用于将多条结构化补丁（Patch）合并、去重、消除冲突，输出精简的统一补丁列表。
   核心特性：

- 层级递归：多轮迭代，每轮按 section 分组并行合并
- Section 感知：同一 section 的 patch 会被分到同一组，避免跨 section 混淆
- 确定性强壮前筛：合并前检测并移除 ADD+DELETE 冲突和 replace 重叠
- 单 Patch 直通：没有同 section 邻居的 patch 直接向上传递，不参与合并
- 并行执行：各组合并任务并发执行
- 容错机制：失败分组原样传递；失败率过高时全局回退到单次批量合并

***

1. 数据结构
   2.1 Patch 对象格式
   {
   "op": "append\_to\_section | insert\_after | insert\_before | replace\_in\_section | replace\_section | add\_after\_section | delete\_section",
   "target\_section": "## 2. Core Instructions",
   "content": "新增内容",
   "reasoning": "合并理由/分析说明"
   }
   2.2 输入格式（Raw Patches）
   文本块，每个 patch 文件以 # File: {filename} 开头，随后是该文件的 JSON patches。

***

1. 算法流程
   3.1 整体架构
   输入: 多条 Raw Patches (# File: blocks)
   │
   ▼
   ┌─────────────────────────────┐
   │ L0: Raw Patch Level │
   │ - 按 branch\_factor 分组 │
   │ - 并行调用 LLM 合并 │
   │ - 输出 JSON Patches │
   └─────────────┬───────────────┘
   │
   ▼
   ┌─────────────────────────────┐
   │ L1+: JSON Patch Level │
   │ (循环直到退出条件满足) │
   │ │
   │ ① deterministic\_guardrail │
   │ - ADD+DELETE 冲突检测 │
   │ - replace 重叠检测 │
   │ │
   │ ② Section-Aware Grouping │
   │ - 同 section 分到同组 │
   │ - 单 patch 直通上层 │
   │ │
   │ ③ 并行调用 LLM 合并 │
   └─────────────┬───────────────┘
   │
   ▼ (达到终止条件)
   ┌─────────────────────────────┐
   │ Root Merge │
   │ - 跨 section 一致性审查 │
   │ - 输出最终合并结果 │
   └─────────────────────────────┘
   3.2 终止条件
   在每层结束时检查，满足以下任一条件则终止递归：
   条件
   patch 数量 ≤ branch\_factor
   已达最大层数 (max\_layers) 且数量 > 1
   patch 数量 = 1 且类型为 json\_patches

***

1. 各阶段详解
   4.1 L0: Raw Patch 合并
   输入： 多条以 # File: 开头的文本块
   处理步骤：
2. Split：按 # File: 分割成 blocks
3. Parse：对每个 block 调用 parse\_structured\_patches() 提取 JSON patches
4. Filter：移除空 patch 块
5. Group：将 blocks 每 branch\_factor 个分为一组
6. Parallel Merge：对每组调用 \_merge\_single\_group() 并行合并
7. Collect Results：收集所有合并结果
   4.2 deterministic\_guardrail（确定性前筛）
   在 L1+ 层每次循环开始时执行，对所有 json\_patches 进行两次冲突检测：
   Pass 1: ADD + DELETE 精确冲突检测
   检测逻辑：

- 对于每个 ADD\_OP（append\_to\_section, insert\_after, insert\_before, add\_after\_section）和 DELETE\_OP（delete\_section）
- 构建 Map: (target\_section, normalized\_content) → indices 列表
- 如果某个 key 同时存在于 ADD 和 DELETE 操作中，则该 key 下的所有 patch 被标记为冲突
  Normalized 方法：

1. 移除所有标点符号（替换为空格）
2. 压缩连续空格为单个空格
3. 转为小写
4. 去除首尾空白
   处理： 冲突的 patch 被移除（detained），不参与后续合并
   Pass 2: replace\_in\_section 重叠检测
   检测逻辑：

- 对于同一 section 内的所有 replace\_in\_section 操作
- 两两比较 old\_text 是否重叠
- 重叠判断：使用 n-gram 算法（n=8, threshold=0.5）
  重叠算法：
  texts\_overlap(a, b, threshold=0.5):
  if a 是 b 的子串 or b 是 a 的子串: return True
  shorter = 较短文本
  longer = 较长文本
  n = min(8, len(shorter))
  if n < 3: return False
  shorter\_ngrams = {所有长度为n的连续子串}
  longer\_ngrams = {所有长度为n的连续子串}
  overlap\_ratio = len(shorter\_ngrams ∩ longer\_ngrams) / len(shorter\_ngrams)
  return overlap\_ratio >= threshold
  处理： 对于重叠的两个 patch，保留 reasoning 较长的，删除另一个
  4.3 Section-Aware Grouping（L1+ 层）
  目的： 确保同一 section 的 patch 被分到同一组进行合并
  算法：
  \_group\_by\_section(patches, branch\_factor):
  sec\_buckets = {} # section -> \[patches]
  no\_section = \[] # 无 section 的 patches

  for p in patches:
  if p.target\_section exists:
  sec\_buckets\[target\_section].append(p)
  else:
  no\_section.append(p)

  groups = \[]
  for section in sorted(sec\_buckets.keys()):
  bucket = sec\_buckets\[section]
  if len(bucket) <= branch\_factor:
  groups.append(bucket)
  else:
  \# 同一 section 的 patches 可能超出 branch\_factor
  \# 按 branch\_factor 分割，但保持在同一组内
  for i in range(0, len(bucket), branch\_factor):
  groups.append(bucket\[i:i+branch\_factor])
  # 无 section 的 patches 也分组
  for i in range(0, len(no\_section), branch\_factor):
  groups.append(no\_section\[i:i+branch\_factor])

  return groups
  特殊处理 - Single Pass：
- 如果一个 patch 在同一 section 内没有邻居（即没有其他 patch 指向同一个 section），则直接加入 single\_pass 列表
- 这些 patch 不会被合并，直接传递到下一层
  4.4 并行合并执行
  流程：

1. 为每个 group 创建并发任务
2. 使用 ThreadPoolExecutor 并行执行 \_merge\_single\_group()
3. 等待所有任务完成，收集结果
   成功时： 将合并结果加入 all\_merged
   失败时： 将原 group 的 items 加入 failed\_passthrough\_\* 列表
   4.5 \_merge\_single\_group（单组合并）
   核心逻辑：
   \_merge\_single\_group(patches\_content, prompt\_structure, input\_type):
   for attempt in range(max\_retries + 1):
   # 构建 LLM 消息
   msg = PATCH\_MERGE\_PROMPT.format(
   prompt\_structure=prompt\_structure,
   patches\_content=patches\_content,
   input\_type=input\_type,
   input\_type\_instruction=INSTRUCTIONS\[input\_type]
   )
   # 调用 LLM
   merged\_raw = call\_llm(msg)
   result = parse\_structured\_patches(merged\_raw)
   # 质量检查：inflation detection
   # 如果输出数量 > 输入数量，认为是质量膨胀
   if result and len(result) > input\_count:
   if attempt < max\_retries:
   wait = 2 \*\* attempt # 指数退避
   sleep(wait)
   continue
   return result, False # 仍然返回但不标记成功

   if result:
   return result, True

   if attempt < max\_retries:
   sleep(2 \*\* attempt)

return \[], False
Inflation Detection：

- 如果输出的 patch 数量 > 输入数量，认为产生了冗余
- 触发重试，使用指数退避（1s, 2s, 4s...）
- 重试次数耗尽后仍然返回，但不标记为成功（后续不会使用）
  4.6 全局回退（Global Fallback）
  触发条件： failure\_rate > PATCH\_MERGE\_FALLBACK\_THRESHOLD
  动作： 将所有原始 blocks 或 patches 合并为一个大分组，执行一次单独的 \_merge\_single\_group()
  4.7 Root Merge（根合并）
  触发场景：
- 层数达到最大值 (max\_layers) 且 patch 数量 > 1
- 其他终止条件下也可能调用
  目的： 最终的跨 section 一致性检查和整合
  模板： 使用 PATCH\_ROOT\_MERGE\_PROMPT 而非 PATCH\_MERGE\_PROMPT，强调跨 section 逻辑冲突检测

***

1. 合并策略指南（LLM Prompt 中的核心原则）
   5.1 结构划分与隔离

- GROUP BY SECTION：按 target\_section 分类，不同 section 不得混淆
- ISOLATION：独特边界情况的 patch 必须完整保留
- 保序性：同 section 内的 append/insert 按业务逻辑顺序排列
  5.2 逻辑去重与泛化
- 去重与拼接：同 section、同 op 的 append 内容直接拼接
- 泛化抽象：将针对个例的指令抽象为通用原则
- 冲突消解：矛盾操作选择 reasoning 更充分的，或调和为独立操作
- 流行度偏置：优先采纳多个独立 patch 中反复出现的修改
  5.3 技术约束
- 独立性：合并后任意两条 edit 不得修改同一行/同一段
- 操作偏置：优先使用 append\_to\_section，避免 replace\_in\_section
- 精简压缩：目标数量 ≤ 输入数量的 1/3

***

1. 配置参数
   参数 默认值
   PATCH\_MERGE\_BRANCH\_FACTOR 8
   PATCH\_MERGE\_MAX\_LAYERS 10
   PATCH\_MERGE\_RETRY\_TIMES 2
   PATCH\_MERGE\_FALLBACK\_THRESHOLD 0.5
   \_texts\_overlap threshold 0.5
   \_texts\_overlap n 8

***

1. 算法伪代码
   FUNCTION run\_parallel\_merge(patches\_content, prompt\_structure):
   blocks = split\_by\_hash\_file(patches\_content)
   IF blocks is empty: RETURN \[]

// L0: Parse raw blocks
block\_patches\_map = \[]
FOR block IN blocks:
patches = parse\_structured\_patches(block)
block\_patches\_map.append((block, patches))

raw\_patches = \[block FOR block, patches IN block\_patches\_map IF patches]
IF raw\_patches is empty: RETURN \[]

input\_type = "raw\_patches"
json\_patches = \[]
layer = 0

WHILE True:
IF input\_type == "json\_patches":
json\_patches = deterministic\_guardrail(json\_patches)

```
current_count = length of (raw_patches if input_type == "raw_patches" else json_patches)

// 终止条件检查
IF current_count <= PATCH_MERGE_BRANCH_FACTOR OR layer >= MAX_LAYERS:
  IF current_count == 0: RETURN []
  IF layer >= MAX_LAYERS AND current_count > 1:
    RETURN root_merge(json_patches, prompt_structure)
  IF current_count == 1 AND input_type == "json_patches":
    RETURN json_patches
  IF input_type == "raw_patches":
    RETURN merge_single_group(raw_patches joined, ...)
  ELSE:
    RETURN root_merge(json_patches, prompt_structure)

// 分组
IF input_type == "raw_patches":
  groups = chunk(raw_patches, BRANCH_FACTOR)
ELSE:
  groupable, single_pass = categorize_by_section(json_patches)
  IF groupable is empty:
    groups = []
  ELSE:
    groups = group_by_section(groupable, BRANCH_FACTOR)

// 并行合并
results = []
failed = []
FOR group IN groups IN PARALLEL:
  result, success = merge_single_group(group, ...)
  IF success:
    results.extend(result)
  ELSE:
    failed.extend(group)

// 失败率检查
IF length(groups) > 0 AND failed.count / groups.count > FALLBACK_THRESHOLD:
  RETURN merge_single_group(all_original_blocks, ...)

// 构建下一层输入
next_patches = results + failed
IF input_type != "raw_patches" AND single_pass:
  next_patches.extend(single_pass)

IF length(next_patches) <= 1:
  RETURN next_patches

json_patches = next_patches
input_type = "json_patches"
layer += 1
```

***

## 8. 时间复杂度分析

- **最坏情况：** O(log\_k(N) × M)，其中 N 是 patch 总数，k 是 branch\_factor，M 是 LLM 调用耗时
- **并行度：** 每层最多 N/k 个并发 LLM 调用
- **空间复杂度：** O(N)，需要存储所有中间结果

***

1. 异常处理
   场景 处理方式
   LLM 返回空 重试最多 max\_retries 次，指数退避
   JSON 解析失败 调用 parse\_structured\_patches() 的 retry + heuristic fallback
   Inflation（数量膨胀） 视为失败，重试
   组内所有合并失败 原样传递到下一层
   失败率过高 全局回退到单次批量合并
   超过最大层数 执行 root merge

