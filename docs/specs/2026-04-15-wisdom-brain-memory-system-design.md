# 智慧大脑 — 活性记忆系统设计

**日期：** 2026-04-15  
**状态：** 已批准  
**范围：** 在 claude-obsidian 中新增双层活性记忆系统，将学习系统与记忆系统合并为统一的智慧大脑。

---

## 1. 背景

当前系统已形成如下闭环：

```
学习系统 (claude-obsidian) → 记忆系统 (Obsidian vault)
决策系统 (cli-assistant)   → 执行系统 (Harness_engineering)
```

**缺口**：Obsidian 是**知识存储库**，不是**工作记忆**。Agent 每次启动新会话，没有"最近在想什么"的感知，必须从头搜索，或依赖用户手动提供上下文。

**目标**：在 Agent 与 Obsidian 之间增加一个活性记忆层，维护最近活跃的概念，对不常用的知识自然衰减，并在每次交互时自动丰富 Agent 的上下文。设计灵感来自 CMS（连续记忆系统）模型和 Hope 架构（自参考 Titans + CMS）。

---

## 2. 设计目标

- Agent 自动"记住"最近使用的概念，无需显式查询
- 记忆随真实时间自然衰减（低频知识淡出）
- 对话或写入新笔记时，相关记忆得到强化
- Obsidian 仍是权威知识库；记忆系统是热缓存层
- v1 不引入 ML 依赖，全程基于关键词匹配
- 单一代码库：所有逻辑均在 claude-obsidian 内

---

## 3. 架构

```
claude-obsidian/
  skills/obsidian/
    memory_manager.py     ← 新增：活性词库管理
    obsidian_writer.py    ← 扩展：写笔记时触发记忆更新
    SKILL.md              ← 扩展：每次调用自动注入记忆上下文

Obsidian Vault/
  _memory.jsonl           ← 新增：长期活性词库（持久化）
  _events.jsonl           ← 已有
  _corrections.jsonl      ← 已有
```

### 双层记忆

| 层 | 存储位置 | 生命周期 | 作用 |
|----|--------|--------|------|
| 短期激活层 | 内存 Python dict | 当前会话 | 本次对话新激活的词 |
| 长期活性库 | `_memory.jsonl` | 跨会话，真实时间衰减 | 持久的活性概念 |

---

## 4. 数据模型

`_memory.jsonl` 每条记录：

```json
{
  "word": "Titans",
  "aliases": ["自参考学习", "test-time"],
  "activation_score": 0.85,
  "frequency": 12,
  "last_activated": "2026-04-15T10:30:00",
  "created": "2026-04-10T09:00:00",
  "decay_rate": 0.05,
  "obsidian_links": ["Literature - Titans论文.md", "Topic - Harness Engineering.md"]
}
```

**字段说明：**
- `decay_rate` 是 per-item 的：高频词衰减慢，低频词衰减快
- `obsidian_links` 支持按需展开：激活某个词后可拉取完整 Obsidian 笔记
- `aliases` 实现联想匹配："自参考学习" → 激活 "Titans"

---

## 5. 激活与遗忘机制

### 激活公式（CMS 启发）

```
activation(t) = base_score × e^(-decay_rate × 距上次访问天数)
              + log(frequency + 1) × 0.1
```

- `base_score`：上次访问时的得分（初始值 1.0）
- `decay_rate`：随访问次数自动调整；高频词约 0.02（慢衰减），低频词约 0.15（快衰减）
- `频率奖励`：防止高频词完全归零的底线

### 典型场景

| 场景 | 结果 |
|------|------|
| 今天刚被强化 | score ≈ 0.9~1.0，出现在注入上下文中 |
| 7 天前学过，未再提起 | score ≈ 0.4~0.6，仍在库中 |
| 30 天无访问、低频词 | score < 0.1，**自动淘汰** |
| 旧词再次出现 | score +0.3，decay_rate × 0.9（变得更难忘） |

### 会话结束时的知识巩固（"睡眠效应"）

```
短期激活层（本次会话激活的词）
  ↓
  ① 已在长期库 → activation++，decay_rate 小幅降低
  ② 不在长期库，且本次激活 ≥ 2 次 → 晋升到长期库
  ③ 只激活 1 次 → 丢弃（噪音过滤）
```

一个词在单次会话内至少出现两次才能进入长期记忆，模拟人类"只有反复印象才固化"的规律。

### 容量上限

长期库默认 **500 条**（可配置）。超出时淘汰 `activation_score` 最低的条目。

---

## 6. 上下文自动注入

### 触发流程

```
用户消息到达
  ↓
SKILL.md 提取关键词（名词、专有词、#标签、[[wikilink]]）
  ↓
memory_manager.query(keywords)
  ├─ 精确匹配 word / aliases
  ├─ 子串匹配（"自参考" → "Titans"）
  └─ 同 obsidian_link 关联
  ↓
返回 top-5 活性词，按 activation_score 排序
  ↓
注入 <active_memory> 块到对话上下文
  ↓
用户说"展开"/"细节"/"给我原文"
  └─ 调用已有 query 能力，从 Obsidian 加载完整笔记
```

### 注入格式（Agent 视角）

```
<active_memory>
● Titans (0.85)  别名: 自参考学习, test-time
  → [[Literature - Titans论文.md]]
● CMS (0.72)  别名: 多频率层, 连续记忆系统
● 遗忘缓解 (0.51)  别名: catastrophic forgetting
</active_memory>
```

### 关键词提取策略（v1，无 ML 依赖）

- 过滤停用词（的/是/了/in/the/a…）
- 保留：英文大写词、中文名词短语（2~4 字）、`#标签`、`[[wikilink]]`
- 匹配记忆条目的 `word` + `aliases` 字段

---

## 7. 记忆写入来源

### 来源 A：Obsidian 写笔记时

`obsidian_writer.py` 写完笔记后自动调用 `memory_manager.extract_and_upsert()`：

```
写入 Literature / Concept / Topic 笔记
  ↓
按笔记类型提取字段：
  - Concept 笔记   → word = 标题，aliases 来自"一句话定义"
  - Literature 笔记 → 从"核心观点"中提取名词短语
  - Topic 笔记     → 从"当前结论"中提取短语
  ↓
写入 _memory.jsonl：
  - 已有词 → frequency++，更新 obsidian_links
  - 新词   → 创建条目，初始 activation_score = 0.6，decay_rate = 0.1
```

### 来源 B：对话中被强化时

```
用户消息命中记忆中的词
  ↓
memory_manager.activate(word)
  - activation_score += 0.3（上限 1.0）
  - decay_rate × 0.9（变得更难忘）
  - last_activated = 当前时间
  ↓
懒写：会话结束时批量 flush 到 _memory.jsonl
      （由 Claude Code Stop hook 触发 → 调用 memory_manager.consolidate_and_flush()）
```

### 两个来源的分工

| 来源 | 产生什么 | 典型词 |
|------|--------|------|
| Obsidian 写入 | 知识体系的概念骨架（冷启动） | Titans、梯度下降、RAG |
| 对话激活 | 最近真正在用的概念（热更新） | Hope架构、智慧大脑、CMS |

Obsidian 建立骨架，对话决定哪些骨架当前是活跃的。

---

## 8. 完整数据流

```
[对话] ──激活──→ [短期激活层] ──巩固──→ [长期活性库 _memory.jsonl]
                                              ↑            ↓
[Obsidian 写入] ──提取────────────────────────             ↓
                                                  自动注入 ↓
[Agent 上下文]  ←──────────── <active_memory> ←───────────
                                      ↑
                              用户说"展开"时
                           从 Obsidian 拉取全文
```

---

## 9. 新增命令

| 命令 | 功能 |
|------|------|
| `/obsidian memory` | 查看当前活性词库 top-20 |
| `/obsidian memory reinforce <词>` | 手动强化某个词 |
| `/obsidian memory forget <词>` | 手动淡忘某个词 |
| `/obsidian memory decay` | 立即运行一次衰减周期 |

---

## 10. v1 范围外

- 语义相似度 / 向量嵌入（v1 只做关键词匹配）
- 跨会话对话内容自动归档到 Obsidian
- 多 vault 记忆共享
- 后台衰减守护进程（衰减在访问时懒执行）

---

## 11. 实现模块

| 模块 | 职责 |
|------|------|
| `memory_manager.py` | 加载/保存 `_memory.jsonl`，查询、激活、衰减、巩固、淘汰 |
| `obsidian_writer.py`（扩展） | 每次写笔记后调用 `extract_and_upsert()` |
| `SKILL.md`（扩展） | 从输入提取关键词，注入 `<active_memory>`，处理 `/obsidian memory` 命令 |

---

## 12. 验收标准

- [ ] 每次交互时，Agent 上下文自动包含 top-5 相关活性词
- [ ] 低频词 30 天以上无访问后自动淘汰
- [ ] 写入 Concept 笔记后，当次会话即可从记忆库中检索到该概念
- [ ] 单次会话内被激活两次的词晋升到长期库
- [ ] `/obsidian memory` 输出可读的活性词排名列表
