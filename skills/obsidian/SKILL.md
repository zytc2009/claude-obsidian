---
description: Write and organize notes in the Obsidian knowledge base. Handles quick fleeting notes, web/file capture, conversation logging, and archiving related notes. Triggered by /obsidian, or natural language like "记一下", "帮我整理这次对话", "抓取这个网页", "把这些笔记归档".
---

You are managing the user's local Obsidian vault at `D:/obsidian/`.

## Step 1: Detect Operation Mode

| User says | Mode |
|-----------|------|
| 记一下, 想到一个, 随手记, fleeting | `fleeting` |
| URL (http/https), 本地文件路径, 帮我抓取, capture | `capture` |
| 整理这次对话, 对话记录, 把我们的讨论存下来, log | `log` |
| 整理归档, 搜索合并, 相关笔记, organize | `organize` |
| 资料笔记, 文章, 论文, 博客, 概念卡, 主题页, 项目, write | `write` |

If still unclear, ask: "你想做什么？fleeting（速记）/ capture（抓取网页/文件）/ log（整理对话）/ organize（归档整理）/ write（写笔记）"

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

**Goal:** 从 URL 或本地文件获取内容，整理成 literature 笔记。

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

### Step C3: 确认标题

用原文章节名或文章标题，不要自己编造。

### Step C4: 写入笔记

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type literature \
  --title "<标题>" \
  --fields '<JSON字段>' \
  --draft false
```

如果提取字段不到一半（`核心观点` 和 `方法要点` 都空），设 `--draft true`。

### Step C5: 提示关联 MOC

检查 `D:/obsidian/03-Knowledge/MOCs/` 下是否有相关 MOC，如有，告知用户可手动添加链接。

---

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
- `D:/obsidian/03-Knowledge/**/*.md`
- `D:/obsidian/00-Inbox/*.md`

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
主题说明, 问题列表, 核心概念, 重要资料, 当前结论, 未解决问题, 下一步路线
```

**project** 字段：
```
项目目标, 完成标准, 当前状态, 任务拆分, 相关资料, 风险与阻塞, 实验记录, 产出
```

### Step W3: 确定草稿状态

设 `--draft true` 如果：
- 用户说"草稿"、"先放 Inbox"
- 提取到的必填字段不足一半

必填字段：
- literature: `核心观点`, `方法要点`
- concept: `一句话定义`, `核心机制`
- topic: `主题说明`, `核心概念`
- project: `项目目标`, `完成标准`, `任务拆分`

### Step W4: 写入笔记

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type <类型> \
  --title "<标题>" \
  --fields '<JSON字段>' \
  --draft <true|false>
```

### Step W5: 提示关联 MOC

检查 `D:/obsidian/03-Knowledge/MOCs/` 下是否有相关 MOC，如有，告知用户。

---

## 最终输出

展示脚本的 stdout。

如果草稿自动触发，补充：
> 内容不完整，已存入 Inbox。建议补充：[列出空缺的必填字段]

如果脚本返回非零，展示 stderr 并说明原因。
