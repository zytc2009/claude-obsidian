# Profile & Article System Implementation

**Date:** 2026-04-19
**Status:** Implemented
**Scope:** Add personal profile management and article generation to `claude-obsidian`

---

## 1. Context

`claude-obsidian` 已经能捕获和组织知识，但缺少两个关键能力：

1. **没有"我是谁"的上下文** — Agent 在写笔记、查询时不知道用户的身份、偏好和项目背景，产出是通用知识而不是个人化知识。

2. **没有"产出"能力** — vault 只进不出，无法把积累的知识合成为可发布的文章，也无法在写新内容时自动查重。

这两个缺口同时影响 MultiAgent 集成的质量：外部 Agent 查询 vault 时拿到的是原始笔记，而不是"经过个人视角过滤的洞察"。

---

## 2. Implemented Behavior

- **G1** 在 vault 内维护结构化个人档案（profile），支持增量更新而非覆盖
- **G2** 支持写入 `article` 类型笔记到 `06-Articles/`，写前自动查重
- **G3** profile 数据注入写作和查询上下文，让产出带有个人视角
- **G4** 为 MultiAgent 集成保留 `query` / `ingest` 接口（当前实现仅提供 CLI 形态）

**Out of Scope:**
- HTTP API / gRPC 服务化
- 文章质量自动评分
- 风格模型训练

---

## 2.1 Implementation Notes

The initial design has been implemented with a few deliberate differences:

- profile management lives in `skills/obsidian/profile_manager.py` as a standalone helper/CLI, rather than adding a dedicated `profile` mode to `obsidian_writer.py`
- article notes are written to `06-Articles/` and use `review` as the non-draft status
- article frontmatter stores `source_notes` and `target_audience` as scalar fields, while the source-note list is also rendered in the body
- `query_vault()` injects profile context into its returned payload and CLI output without changing the existing CLI surface area
## 3. Implementation Details

### 3.1 Vault 结构扩展

```
vault/
├── 05-Profile/               ← 新增
│   ├── Profile - Personal.md      # 姓名、地点、职业、家庭、兴趣
│   ├── Profile - Projects.md      # 活跃项目、目标、常讨论话题
│   ├── Profile - Tooling.md       # 工具、语言、框架、技术栈
│   └── Profile - Preferences.md   # AI 行为纠正和偏好记录
└── 06-Articles/              ← 新增
    └── Article - [标题].md
```

### 3.2 Profile 笔记模型

Profile 笔记的核心特性：**upsert 而非 create**。每次更新只合并 diff，不覆盖已有内容。

**frontmatter：**
```yaml
---
type: profile
subtype: personal | projects | tooling | preferences
updated: YYYY-MM-DD
version: N        # 每次 upsert +1
---
```

**Profile - Personal.md 字段结构：**
```markdown
# Personal

## 基本信息
- 姓名：
- 所在地：
- 职业：
- 家庭：

## 兴趣爱好

## 背景与经历
```

**Profile - Projects.md 字段结构：**
```markdown
# Projects

## 活跃项目
<!-- 每项：[[项目名]] — 一句话描述 — 当前阶段 -->

## Note Structures
<!-- 短期 / 中期 / 长期 -->

## 常讨论话题
<!-- 高频关键词列表 -->
```

**Profile - Tooling.md 字段结构：**
```markdown
# Tooling

## 编程语言

## 框架与库

## 工具链

## AI 工具
```

**Profile - Preferences.md 字段结构：**
```markdown
# Preferences

## AI 行为偏好
<!-- 格式：[日期] 场景 → 期望行为 -->

## 纠正记录
<!-- 格式：[日期] 错误行为 → 正确做法 → 原因 -->

## 写作风格偏好
```

### 3.3 Profile Upsert 逻辑

`profile_manager.py` 负责 profile 的读写：

```
upsert_profile(vault, subtype, updates: dict) → Path
  1. 读取已有笔记（若不存在则从模板创建）
  2. 按 section 标题匹配，将 updates 中的内容追加到对应 section
  3. 更新 frontmatter.updated 和 frontmatter.version
  4. 写回文件
  5. 返回文件路径

read_profile(vault, subtype=None) → str
  返回指定 subtype（或全部）的 profile 内容，供上下文注入
```

**合并策略：**
- `基本信息` 等 key-value 类 section：已有 key 不覆盖，新 key 追加
- `纠正记录` / `AI 行为偏好` 等 log 类 section：直接追加到末尾（带时间戳）
- `活跃项目` 等列表类 section：按 `[[项目名]]` 去重追加

### 3.4 Article 笔记模型

**frontmatter：**
```yaml
---
type: article
status: draft | review | published
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: []
source_notes: []    # wikilinks to source notes in vault
target_audience: "" # 目标读者
---
```

**正文结构：**
```markdown
# [标题]

## 核心论点

## 正文

## 结语

## 来源
<!-- source_notes 的可读展开 -->
```

### 3.5 查重机制

写入 article 前执行两层检查：

**Layer 1 — 标题相似度（快速，无 LLM）：**
```
candidate_stem = normalize(title)   # 去标点、小写、去停用词
for existing in vault/06-Articles/*.md:
    ratio = similarity(candidate_stem, existing.stem)
    if ratio > 0.8:
        warn + return existing_path  # 不写入，返回已有文件
```

相似度算法：使用 `difflib.SequenceMatcher`，无额外依赖。

**Layer 2 — 来源重叠（写入后可选）：**
- 检查 `source_notes` 与已有 article 的 `source_notes` 交集
- 交集 > 60% 时在 frontmatter 写入 `related_articles` 提示，不阻断写入

### 3.6 Profile 上下文注入

写 article 或执行 query 时，自动读取 profile 注入上下文：

```
context = read_profile(vault)
# 注入到 SKILL.md 的提示前缀：
# "用户背景：{context}\n写作时保持个人视角..."
```

query 模式下，profile 的"常讨论话题"用于扩展关键词：
```
base_query = user_input
expanded = base_query + profile.frequent_topics (overlapping terms)
```

### 3.7 MultiAgent Entry Points (CLI Only)

```bash
# 查询
python obsidian_writer.py --mode query --question "RAG 的核心挑战" --profile true

# 入库（聊天记录摘要）
python obsidian_writer.py --mode ingest --source chat \
  --title "MultiAgent 架构讨论" --fields '{...}'
```

内部调用已有 `query_vault()` 和 `write_note()`，profile 注入通过 `read_profile()` 实现。

---

## 4. Data Flow

```
用户输入 / 外部 Agent 调用
        ↓
SKILL.md 意图识别
        ↓
┌─────────────────────────────────┐
│   profile 操作？                │
│   → profile_manager.upsert()   │
│                                 │
│   article 写入？                │
│   → _check_duplicate()          │
│   → render_article()            │
│   → write_note() → 06-Articles/ │
│                                 │
│   query？                       │
│   → read_profile() 注入上下文   │
│   → query_vault()               │
└─────────────────────────────────┘
        ↓
Obsidian Vault（读/写）
```

---

## 5. File Changes

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `skills/obsidian/profile_manager.py` | 新建 | profile upsert / read 逻辑 |
| `skills/obsidian/obsidian_writer.py` | 修改 | 加 article 类型、_check_duplicate、profile 注入 |
| `skills/obsidian/SKILL.md` | 修改 | 加 profile 和 article 操作说明 |
| `tests/test_profile_manager.py` | 新建 | profile upsert / read 测试 |
| `tests/test_article.py` | 新建 | article 写入和查重测试 |
| `docs/specs/` | 本文件 | 实现说明 |

---

## 6. Decisions and Deferred Items

- **Q1:** Profile - Preferences.md 是否与 Claude Code 的 memory 系统（`~/.claude/projects/.../memory/`）同步？
  - **Decision:** 不同步，独立维护。
  - **Reason:** vault 属于用户数据，Claude memory 属于模型侧工作记忆，两者目标不同。
  - **Status:** 已落地为独立的 `skills/obsidian/profile_manager.py`。
- **Q2:** article 的"风格"如何量化存储？
  - **Decision:** 当前实现不做风格向量化。
  - **Implemented as:** 以 `Profile - Preferences.md` 保存纯文本偏好，由 `SKILL.md` 提醒 Claude 读取并应用。
  - **Status:** 作为后续增强项保留。
- **Q3:** `ingest` 接口的入口是否需要鉴权？
  - **Decision:** 当前 CLI 形态不需要。
  - **Status:** 若未来服务化，再单独补鉴权层。

---

## 7. Implementation Summary

This spec records the implemented behavior rather than a proposal.

- Profile management is implemented in `skills/obsidian/profile_manager.py`
- Article notes are implemented in `skills/obsidian/obsidian_writer.py`
- Query output includes profile context when profile notes exist
- The accompanying plan and tests have been completed and verified
