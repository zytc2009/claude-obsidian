---
description: Write and organize notes in the Obsidian knowledge base. Handles quick fleeting notes, web/file capture, conversation logging, and archiving related notes. Triggered by /obsidian, or natural language like "记一下", "帮我整理这次对话", "抓取这个网页", "把这些笔记归档".
---

You are managing the user's local Obsidian vault. The default path is `~/obsidian/`, but check the `OBSIDIAN_VAULT_PATH` environment variable first — the user may have configured a custom path.

## Step 1: Detect Operation Mode

| User says | Mode |
|-----------|------|
| 记一下, 想到一个, 随手记, fleeting | `fleeting` |
| URL (http/https), 本地文件路径, 帮我抓取, capture | `capture` |
| 整理这次对话, 对话记录, 把我们的讨论存下来, log | `log` |
| 整理归档, 搜索合并, 相关笔记, organize | `organize` |
| 资料笔记, 文章, 论文, 博客, 概念卡, 主题页, 项目, write | `write` |
| 初始化, 创建目录, 初次使用, init | `init` |
| 检查知识库, lint, vault 健康检查, 断链, 孤立笔记 | `lint` |
| 在笔记里查, 知识库搜索, query, 我笔记里有关…的内容 | `query` |
| 重建索引, 更新 index, 生成目录, rebuild index | `index` |

If still unclear, ask: "你想做什么？fleeting（速记）/ capture（抓取网页/文件）/ log（整理对话）/ organize（归档整理）/ write（写笔记）/ query（知识库问答）/ lint（健康检查）/ init（初始化目录）"

---

## MODE: fleeting — 闪念速记

**Goal:** 极简记录，追加到当天 DailyNote 的 Fleeting 区块。

1. 从用户消息中提取：
   - `content`: 想法正文（必填）
   - `tags`: 可选标签，格式 `#tag1 #tag2`

2. 调用脚本：
```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type fleeting \
  --fields '{"content": "<内容>", "tags": "<标签>"}'
```

3. 展示 `[OK] Appended to: ...`，无需确认。

---

## MODE: capture — 抓取外部内容

**Goal:** 从 URL 或本地文件获取内容，整理成 literature 笔记。默认走 ingest-sync 路径：提取完字段后先出 preview，用户一次性确认再写入。

### Step C1: 获取原始内容

- **URL**: 用 WebFetch 工具抓取页面内容
- **本地文件**: 用 Read 工具读取文件内容
- 内容过长时，分段阅读，确保覆盖全文

### Step C2: 提取字段

从获取的内容中提取以下字段（密集详细，不要简化）：

**CRITICAL:** 目标是让用户几周后重读笔记，能获取原文 80% 的信息量。

- `source`: 原始 URL 或文件路径
- `author`: 作者
- `类型`: 文章 / 论文 / 博客 / 教程 / 视频文字稿 / 其他
- `解决的问题`: 这份资料试图解决什么问题
- `核心观点`: 多段，保留完整逻辑链，含 why 和 how
- `方法要点`: 具体步骤、数字、阈值、例子、边界情况
- `细节`: 具体数据点、引用、实验结果、令人意外的事实
- `原文主要内容`: 按原文章节结构重建，保留深度，这是最长的字段
- `存疑之处`: 具体的质疑或问题
- `可转化概念`: 值得提炼为概念卡的名词
- `验证实验`: 可以做哪些实验验证
- `知识连接`: 与已有笔记的关联

标题直接取原文标题，不要自己编造。

### Step C3: 置信度判断

判断是否满足"高置信度"条件（两项必填字段均有内容）：

- `核心观点` 已填写
- `方法要点` 已填写

**低置信度**（任意一项为空）→ 直接走 **create-only 路径**（Step C4b），跳过 preview。
**高置信度** → 走默认的 **ingest-sync 路径**（Step C4a）。

### Step C4a: Ingest preview（高置信度，默认路径）

先跑 `--dry-run` 生成 ingest plan，展示给用户：

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type literature \
  --title "<标题>" \
  --fields '<JSON字段>' \
  --draft false \
  --dry-run
```

输出包含：
- `Action`：`create`（新笔记）或 `merge`（已有同名笔记，将创建带日期副本）
- `Target`：目标路径
- `Existing` + `Diff`：如果是 merge，显示现有笔记与新内容的 section 差异
- `[Link suggestions]`：写入后会被建议关联的 topic/MOC

展示 preview 后，询问用户：**"确认写入？(y/n)"**

收到确认后执行 Step C5 写入。用户说"不"或要求修改，则按反馈调整字段后重新 preview。

### Step C4b: Create-only（低置信度回退路径）

字段不足，直接写入 Inbox，不出 preview：

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type literature \
  --title "<标题>" \
  --fields '<JSON字段>' \
  --draft true
```

告知用户：草稿已存入 Inbox，建议补充：[列出空缺的必填字段]

### Step C5: 执行写入（ingest-sync 路径专用）

用户确认 preview 后执行实际写入：

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type literature \
  --title "<标题>" \
  --fields '<JSON字段>' \
  --draft false
```

### Step C6: 关联建议

脚本输出 `[Link suggestions]`，询问是否自动添加链接。
如果用户确认，用 Read + Edit 工具将 `[[新笔记名]]` 添加到建议的区块末尾。

---

## Capture Addendum: Merge-First Literature Workflow

When `capture` is writing a `literature` note, do not assume every new source should create a new file.

Use this decision order:

1. Run:

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type merge-candidates \
  --title "<source title>"
```

2. If there are no candidates, create a new `literature` note as usual.
3. If there are candidates, read the top 1-3 candidate notes and decide whether the new source:
   - covers the same primary subject
   - advances the same core thesis
   - mostly adds evidence, benchmarks, boundary conditions, or nuance
4. Only merge when all three are substantially true.
5. If confidence is low, create a new note instead of merging.

If you decide to merge, synthesize the updated sections first, then call:

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type merge-update \
  --target "<target note path relative to vault>" \
  --fields '<JSON with updated sections>' \
  --source-note "Literature - <new source title>" \
  --source-ref "<author or publication>, <date>"
```

Minimum merge sections for `literature`:

- `核心观点`
- `方法要点`

Optional merge sections when materially affected:

- `原文主要内容`
- `值得记住的细节`
- `我不认同或存疑的地方`

The script will:

- replace or append the supplied sections
- add the source under `# Sources`
- add the new source note under `# Supporting notes`
- append a `merge` entry to `_log.md`
- refresh the target note's `updated` field

After creating or merging a `literature` note, do a narrow topic cascade check:

1. Run:

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type cascade-candidates \
  --target "<literature note path relative to vault>"
```

2. Read the top 1-3 topic candidates.
3. Only cascade-update when the new source materially changes synthesis, such as:
   - it changes the current conclusion
   - it adds a key supporting reference
   - it resolves an open question
   - it introduces a real contradiction
4. Do not cascade-update on keyword overlap alone.

If a topic should be updated, call:

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type cascade-update \
  --target "<topic note path relative to vault>" \
  --fields '<JSON with updated topic sections>' \
  --source-note "Literature - <new source title>"
```

Allowed cascade sections are intentionally narrow:

- `主题说明`
- `核心问题`
- `重要资料`
- `相关项目`
- `当前结论`
- `未解决问题`

If confidence is low, skip cascade-update entirely.

Successful cascade updates also refresh the target topic note's `updated` field.

When a new source concretely disagrees with an existing note, do not silently overwrite the old claim.

Use `conflict-update` when all of these are true:

- the disagreement is specific, not just a different emphasis
- the new source and old note make materially incompatible claims
- the conflict matters for future synthesis

Call:

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type conflict-update \
  --target "<topic or concept note path relative to vault>" \
  --fields '{"claim": "<new conflicting claim>"}' \
  --source-note "Literature - <new source title>" \
  --conflicts-with "<existing note or claim reference>"
```

Default status is `unresolved`. Only use a different status label when the user or the evidence clearly resolves the disagreement.

Adding a new conflict annotation also refreshes the target note's `updated` field.

When you already know the full deterministic plan, prefer a single `ingest-sync` call instead of chaining `merge-update`, `cascade-update`, and `conflict-update`.

Use this shape:

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type ingest-sync \
  --target "<primary literature note path relative to vault>" \
  --fields '{
    "primary_fields": {...},
    "source_note": "Literature - <new source title>",
    "source_ref": "<author or publication>, <date>",
    "cascade_updates": [
      {"target": "<topic path>", "fields": {...}}
    ],
    "conflicts": [
      {"target": "<topic or concept path>", "claim": "...", "conflicts_with": "..."}
    ]
  }'
```

This keeps all reasoning in the skill while reducing shell round-trips and ensuring the log captures the whole ingest as one operation.

## MODE: log — 对话转文档

**Goal:** 把当前对话整理成一篇完整笔记，保留信息密度。

### Step L1: 分析对话内容，选择笔记类型

| 对话性质 | 推荐类型 |
|---------|---------|
| 技术调研、学习某个知识点 | `literature` |
| 围绕某个主题的深度讨论 | `topic` |
| 项目规划、功能设计 | `project` |
| 某个具体概念的拆解 | `concept` |

告知用户你选择的类型和理由，等确认（或让用户选择其他类型）。

### Step L2: 提取内容

从对话中提取对应类型的所有字段（参见各类型字段定义）。  
特别注意：保留对话中的具体决策、数据、代码片段、推理过程——不要抽象简化。

### Step L3: 确认标题和字段

展示提取的关键字段给用户确认，等确认后再写入。

### Step L4: 写入笔记

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type <类型> \
  --title "<标题>" \
  --fields '<JSON字段>' \
  --draft false
```

---

## MODE: organize — 搜索、合并、归档

**Goal:** 把 vault 中相关笔记整理成一个有结构的 topic 或 MOC。

### Step O1: 搜索相关笔记

用 Glob 和 Grep 工具在 vault 中搜索：
- `$OBSIDIAN_VAULT_PATH/03-Knowledge/**/*.md`
- `$OBSIDIAN_VAULT_PATH/00-Inbox/*.md`

按关键词搜索标题和内容，列出匹配的笔记文件。

### Step O2: 展示匹配列表

告知用户找到了哪些相关笔记，让用户确认要合并哪些。

### Step O3: 读取并合并内容

用 Read 工具读取所选笔记，提炼：
- 不重复的核心观点
- 共同引用的概念
- 未解决的问题
- 各笔记的链接

### Step O4: 写入 topic 或 MOC

如果内容较浅（只有链接列表）→ 写 `moc`  
如果有实质性综合内容 → 写 `topic`

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type topic \
  --title "<主题名>" \
  --fields '<JSON字段>' \
  --draft false
```

### Step O5: 归档 Inbox 笔记

告知用户哪些 Inbox 笔记已经被整合，建议手动移至对应目录或 `04-Archive`。

---

## MODE: write — 写入单篇笔记

### Step W1: 识别笔记类型

| 用户说 | 类型 |
|--------|------|
| 资料笔记, literature, 文章, 论文, 博客 | `literature` |
| 概念卡, concept, 概念 | `concept` |
| 主题页, topic, 主题 | `topic` |
| 项目页, project, 项目 | `project` |

### Step W2: 提取字段

**literature** 字段（密集详细，参见 capture 模式的字段说明）：
```
source, author, 类型, 解决的问题, 核心观点, 方法要点, 细节, 原文主要内容, 存疑之处, 可转化概念, 验证实验, 知识连接
```

**concept** 字段：
```
一句话定义, 解决什么问题, 核心机制, 关键公式或流程, 优点, 局限, 适用场景, 常见误区, 我的理解, 相关链接
```

**topic** 字段：
```
主题说明, 核心问题, 重要资料, 相关项目, 当前结论, 未解决问题
```

**project** 字段：
```
项目描述, 原因分析, 排查过程, 解决方案, 结果验证, 风险与遗留问题
```

### Step W3: 确定草稿状态

设 `--draft true` 如果：
- 用户说"草稿"、"先放 Inbox"
- 提取到的必填字段不足一半

必填字段：
- literature: `核心观点`, `方法要点`
- concept: `一句话定义`, `核心机制`
- topic: `主题说明`, `当前结论`
- project: `项目描述`, `排查过程`, `解决方案`

### Step W4: 写入笔记

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type <类型> \
  --title "<标题>" \
  --fields '<JSON字段>' \
  --draft <true|false>
```

### Step W5: 关联建议

脚本会自动输出 `[Link suggestions]`，优先展示可能归属的 `topic`，其次才是 `MOC`。
建议中可能带有 `strength=...`、`title=...`、`body=...`，用于说明推荐原因。
这些建议的主要作用是帮助用户发现主题归属，而不是盲目自动加链接。
如果没有强 `topic` 匹配，脚本还可能输出 `[Topic suggestion]`，提示用户考虑新建一个主题页。
如果用户确认，用 Read + Edit 工具将 `[[新笔记名]]` 添加到建议的区块末尾。

---

## MODE: init — 初始化目录结构

**Goal:** 首次使用时创建 vault 所需的所有目录，完成后展示目录树确认。

```bash
python ~/.claude/scripts/obsidian_writer.py --type init
```

直接展示脚本输出，无需额外处理。

---

## MODE: query — 知识库问答

**Goal:** 搜索 vault 中的已有笔记回答用户问题，每个论点附引用来源，可选归档答案。

### Step Q1: 搜索相关笔记

用 Grep 工具在以下位置搜索用户问题中的关键词：
- `$OBSIDIAN_VAULT_PATH/03-Knowledge/**/*.md`
- `$OBSIDIAN_VAULT_PATH/02-Projects/**/*.md`

搜索标题和正文，列出匹配文件。

### Step Q2: 读取笔记内容

用 Read 工具读取匹配笔记的相关段落（优先读 `核心观点`、`当前结论`、`一句话定义` 区块）。

### Step Q3: 综合回答

基于找到的内容回答，每个论点标注来源：

```
Transformer 的核心是自注意力机制 — [[Concept - Self-Attention]]
在实际部署中 KV Cache 是主要瓶颈 — [[Literature - LLM Inference Optimization]]
```

如果 vault 中没有相关内容，明确告知："你的笔记里暂无关于 X 的内容。"

### Step Q4: 可选归档

如果用户说"存下来"、"保存这个回答"：

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type topic \
  --title "<问题主题>" \
  --fields '{"主题说明": "...", "当前结论": "...", "重要资料": "[[...]]"}' \
  --draft false
```

---

## MODE: lint — 知识库健康检查

**Goal:** 扫描 vault，报告质量问题，可选自动修复简单问题。

### 检查项

| 类型 | 说明 | 处理 |
|------|------|------|
| 断链 | `[[wikilink]]` 指向不存在的笔记 | 报告 |
| 孤立笔记 | 03-Knowledge / 02-Projects 下未被任何笔记引用的文件 | 报告 |
| Inbox 积压 | 00-Inbox 中超过 7 天的笔记 | 报告 |
| 空壳笔记 | `_待补充_` 占比超过 50% 的笔记 | 报告 |
| 陈旧笔记 | status=active 且 90 天未更新 | 报告 |
| 缺失 frontmatter 字段 | 缺少 status/created/updated/reviewed | 自动修复（需 `--auto-fix`） |

### 调用

```bash
# 仅报告
python ~/.claude/scripts/obsidian_writer.py --type lint

# 报告 + 自动修复 frontmatter
python ~/.claude/scripts/obsidian_writer.py --type lint --auto-fix
```

### 使用时机

- 用户说"检查知识库"、"lint"、"有没有断链"、"孤立笔记" → 直接运行，展示输出
- 用户说"帮我修复"、"自动修复"、"fix" → 加 `--auto-fix` 运行

---

## MODE: index — 知识库索引维护

**Goal:** 在 vault 根目录生成/重建 `_index.md`，作为全局导航页。

> 写入新笔记（write/capture）时会自动增量更新索引，无需手动触发。
> 仅在索引混乱或首次使用时需要重建。

```bash
python ~/.claude/scripts/obsidian_writer.py --type index
```

直接展示脚本输出。索引文件位于 vault 根目录的 `_index.md`。

---

## 最终输出

展示脚本的 stdout。

如果草稿自动触发，补充：
> 内容不完整，已存入 Inbox。建议补充：[列出空缺的必填字段]

如果脚本返回非零，展示 stderr 并说明原因。
