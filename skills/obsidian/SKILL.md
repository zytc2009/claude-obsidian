---
description: Write and organize notes in the Obsidian knowledge base. Handles quick fleeting notes, web/file capture, conversation logging, and archiving related notes. Triggered by /obsidian, or natural language like "记一下", "帮我整理这次对话", "抓取这个网页", "把这些笔记归档".
---

You are managing the user's local Obsidian vault. The default path is `~/obsidian/`, but check the `OBSIDIAN_VAULT_PATH` environment variable first — the user may have configured a custom path.

## 会话启动：注入分层记忆上下文

每次被调用时，按以下顺序加载记忆上下文：

1. **先看 session memory**：如果 vault 根目录存在 `_session_memory.json`，先读取它，把其中的：
   - `active_topics`
   - `active_notes`
   - `recent_queries`
   - `rejected_targets`
   - `open_loops`

   视为当前会话的工作记忆。

2. **再看 activation memory**：运行以下命令获取当前活性记忆：

```bash
python ~/.claude/skills/obsidian/memory_manager.py \
  --vault "${OBSIDIAN_VAULT_PATH:-~/obsidian}" \
  --mode query \
  --keywords "<关键词>"
```

使用规则：

- 优先参考 `_session_memory.json` 中的当前焦点和本会话拒绝记录
- 再参考 `<active_memory>...</active_memory>` 中的长期活性记忆
- 若两者冲突，以 session memory 为准，因为它代表当前会话状态
- 当 `<active_memory>` 中出现 `Topic - ... (topic, score)` 行时，优先从该 topic 出发组织回答，而不是直接落到零散 literature

**关键词提取规则：** 从用户消息中提取名词、英文大写词、`#标签`、`[[wikilink]]`，过滤停用词（的/是/了/in/the 等）。

---

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
| 找孤儿笔记, 聚类整理, 批量建主题, topic scout | `topic-scout` |
| memory, 记忆状态, 活性词, 强化, 淡忘 | `memory` |

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

### Step C6: 关联建议与 topic 归属

脚本输出 `[Link suggestions]`，询问是否自动添加链接。
如果用户确认，用 Read + Edit 工具将 `[[新笔记名]]` 添加到建议的区块末尾。

**Topic 归属检查（必做）：**

- 如果 `[Link suggestions]` 里有 topic 命中（路径包含 `Topics/`）→ 询问是否把 `[[新笔记名]]` 加到该 topic 的 `## 重要资料` 区块
- 如果没有 topic 命中，且脚本输出了 `[Topic suggestion]` → **主动追问用户**：

  > "这篇笔记暂时没有归属的主题页。建议新建：`<proposed topic name>`
  > [1] 现在新建这个主题页
  > [2] 关联到其他已有主题（请告诉我主题名）
  > [3] 暂不归属（会在下次 lint 中标记为孤儿）"

  等用户选择后执行，不要跳过此步骤。

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

## Capture Addendum: Platform Routing and Relation Extraction

Capture now routes URLs through a small platform detector before writing:

- `mp.weixin.qq.com` -> `skills/obsidian/importers/wechat.py`
- `www.xiaohongshu.com` / `xhslink.com` / `xiaohongshu.com` -> `skills/obsidian/importers/xiaohongshu.py`
- everything else -> generic HTML capture

Recommended flow:

1. Run `python skills/obsidian/importers/router.py --url <url>` to inspect the imported payload.
2. Fill the literature fields from the imported title/content/summary.
3. Call `obsidian_writer.py --type capture --url <url> --fields '<JSON>'` to write the note.

If `OBSIDIAN_RELATION_EXTRACT=1` and `ANTHROPIC_API_KEY` is available, the writer also runs relation extraction after a successful write and appends `## 相关概念` links non-fatally.

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

### Step L5: Topic 归属检查（必做）

脚本输出 `[Link suggestions]` 和可能的 `[Topic suggestion]`。

- 如果有 topic 命中 → 询问是否关联
- 如果没有 topic 命中 → **主动追问**：

  > "这篇笔记暂时没有归属的主题页。建议新建：`<proposed topic name>`
  > [1] 现在新建这个主题页
  > [2] 关联到其他已有主题（请告诉我主题名）
  > [3] 暂不归属（会在下次 lint 中标记为孤儿）"

---

## MODE: organize — 搜索、合并、归档

在 `organize` / `query` / topic 归属决策中，检索顺序固定为：

1. session memory 中的 `active_topics` / `active_notes`
2. activation memory 中的 topic / concept
3. vault 中的 topic notes
4. vault 中的 literature / project / concept notes

如果某个 target 在 `_session_memory.json.rejected_targets` 里已经被当前 source note 拒绝过，本次会话中不要再次把它当作优先建议。

**Goal:** 把 vault 中相关笔记整理成一个有结构的 topic 或 MOC。

### Step O1: 搜索相关笔记

直接调用 organize CLI：

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type organize \
  --query "<主题或关键词>"
```

脚本会：

- 先看 session memory 中的当前 topic / note
- 再搜索 `03-Knowledge/` 和 `00-Inbox/` 中的相关笔记
- 输出 `[Session-first]` 和 `[Matches]`
- 给出 `[Suggest] Converge into: topic|moc`
- 在没有强 topic 命中时给出 `[Topic suggestion]`

### Step O2: 展示匹配列表

告知用户找到了哪些相关笔记，让用户确认要整合哪些。

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

### Step W5: 关联建议与 topic 归属

脚本会自动输出 `[Link suggestions]`，优先展示可能归属的 `topic`，其次才是 `MOC`。
建议中可能带有 `strength=...`、`title=...`、`body=...`，用于说明推荐原因。
如果用户确认关联，用 Read + Edit 工具将 `[[新笔记名]]` 添加到建议的区块末尾。

**Topic 归属检查（必做）：**

- 如果 `[Link suggestions]` 里有 topic 命中 → 询问是否把 `[[新笔记名]]` 加到该 topic 的 `## 重要资料` 区块
- 如果没有 topic 命中，且脚本输出了 `[Topic suggestion]` → **主动追问用户**：

  > "这篇笔记暂时没有归属的主题页。建议新建：`<proposed topic name>`
  > [1] 现在新建这个主题页
  > [2] 关联到其他已有主题（请告诉我主题名）
  > [3] 暂不归属（会在下次 lint 中标记为孤儿）"

  等用户选择后执行，不要跳过此步骤。

---

## MODE: init — 初始化目录结构

**Goal:** 首次使用时创建 vault 所需的所有目录，完成后展示目录树确认。

```bash
python ~/.claude/scripts/obsidian_writer.py --type init
```

直接展示脚本输出，无需额外处理。

---

## MODE: query — 知识库问答

**Goal:** 两段式检索——先从 topic 综述给出简答，用户需要细节时再 drill down 到 literature。

### Step Q1: Tier 1 — 搜索 topic 综述

直接调用查询 CLI：

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type query \
  --query "<用户问题>"
```

脚本会按以下顺序检索：

1. session memory
2. active memory
3. topic notes

默认输出 `[Tier 1: Topics]`，只包含 topic 的：
- `主题说明`
- `当前结论`
- `未解决问题`

**如果 Tier 1 有命中，先输出简答，然后询问用户：**
> "需要看原始资料吗？（说"展开"或"细节"进入详细模式）"

**如果 Tier 1 无命中，直接进入 Tier 2。**

### Step Q2: Tier 2 — drill down（按需）

当用户说"展开"、"细节"、"给我原文"、"原始资料"时，或 Tier 1 无命中时，调用：

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type query \
  --query "<用户问题>" \
  --details
```

脚本会输出：

- `[Tier 2: Details]`：按 topic 分组的 literature / concept / project 命中
- `[Orphans]`：无 topic 父节点的命中

如果脚本返回 `[Query] No matches for: ...`，明确告知："你的笔记里暂无关于 X 的内容。"

### Step Q3: 可选归档

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

## MODE: topic-scout — 孤儿笔记聚类

**Goal:** 扫描 `00-Inbox/` 和 `03-Knowledge/`（不含 `Topics/`），找出所有没有 topic 父节点的笔记，按词汇相似度聚类，提出建议 topic。

```bash
python ~/.claude/scripts/obsidian_writer.py --type topic-scout
```

脚本输出：
- 每个 cluster 的建议 topic 名 + 成员笔记列表
- 无法归入 cluster 的单独列出（Singletons）

**当用户确认某个 cluster 时：**

1. 取建议名作为标题（用户可修改）
2. 调用 `write` 模式新建 topic 笔记，`重要资料` 预填 cluster 成员的 `[[wikilink]]` 列表
3. 可选：在每篇 cluster 成员笔记里反向添加 `[[Topic - 新名]]` 链接（询问用户后执行）

**运行频率：** 按需触发，不自动运行。建议在 `lint` 发现大量孤儿后手动跑。

---

## MODE: memory — 活性记忆管理

**Goal:** 查看、强化或淡忘活性词库中的词条。注意：这是长期活性记忆，不等于 session memory。

### 子命令

| 用户说 | 操作 |
|--------|------|
| `/obsidian memory` 或 "记忆状态" | 显示 top-20 活性词 |
| `/obsidian memory reinforce <词>` 或 "强化 <词>" | 手动提升激活分数 |
| `/obsidian memory forget <词>` 或 "淡忘 <词>" | 从活性库中删除 |
| `/obsidian memory decay` 或 "运行衰减" | 立即执行衰减周期 |

### 执行命令

**显示状态：**
```bash
python ~/.claude/skills/obsidian/memory_manager.py \
  --vault "${OBSIDIAN_VAULT_PATH:-~/obsidian}" \
  --mode status
```

**强化词条：**
```bash
python ~/.claude/skills/obsidian/memory_manager.py \
  --vault "${OBSIDIAN_VAULT_PATH:-~/obsidian}" \
  --mode reinforce \
  --word "<词>"
```

**淡忘词条：**
```bash
python ~/.claude/skills/obsidian/memory_manager.py \
  --vault "${OBSIDIAN_VAULT_PATH:-~/obsidian}" \
  --mode forget \
  --word "<词>"
```

**运行衰减：**
```bash
python ~/.claude/skills/obsidian/memory_manager.py \
  --vault "${OBSIDIAN_VAULT_PATH:-~/obsidian}" \
  --mode decay
```

---

## 最终输出

展示脚本的 stdout。

如果草稿自动触发，补充：
> 内容不完整，已存入 Inbox。建议补充：[列出空缺的必填字段]

如果脚本返回非零，展示 stderr 并说明原因。

---

## PROFILE / ARTICLE EXTENSIONS

### `profile` — 更新个人档案

更新 vault 中的个人档案笔记。子类型包括：
- `personal`：基本信息、兴趣爱好、背景与经历
- `projects`：活跃项目、目标、常讨论话题
- `tooling`：编程语言、框架与库、工具链、AI 工具
- `preferences`：AI 行为偏好、纠正记录、写作风格偏好

建议使用：
```bash
python ~/.claude/skills/obsidian/profile_manager.py \
  --vault "${OBSIDIAN_VAULT_PATH:-~/obsidian}" \
  --mode upsert \
  --subtype personal \
  --section "基本信息" \
  --content "姓名: Alice"
```

读取全部档案：
```bash
python ~/.claude/skills/obsidian/profile_manager.py \
  --vault "${OBSIDIAN_VAULT_PATH:-~/obsidian}" \
  --mode read
```

### `article` — 写文章

将知识库内容整合为可发布文章，写入 `06-Articles/`。非草稿状态默认使用 `review`，并在写入前做重复标题检查；相似度过高时复用现有文章而不是新建文件。

示例：
```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type article \
  --title "RAG Writing" \
  --fields '{"核心论点":"...","正文":"...","结语":"...","source_notes":"[[Literature - RAG Survey]]","target_audience":"Engineers"}'
```
