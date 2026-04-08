# 用 Claude Code 直接写 Obsidian 笔记

你在 Claude Code 里和 AI 聊了半小时，得到一篇不错的技术分析。然后你打开 Obsidian，新建笔记，把内容手动复制过去，调格式，加 frontmatter，放进正确的目录。

这个流程我重复了几十次之后决定解决它。

`claude-obsidian` 是一个 Claude Code skill，让你在任何 Claude 会话里用一行自然语言把内容写进 Obsidian vault，不切换窗口，不复制粘贴，不手动排版。

最近把它从六种操作扩展到十种，加入了知识库问答、健康检查、关联建议和自动索引。这篇文章把新功能一并介绍。

---

## 它能做什么

十种操作，覆盖从初始化到知识库维护的完整场景：

| 操作 | 触发方式 | 结果 |
|------|---------|------|
| `init` | "初始化" / "init" | 创建 vault 目录结构 |
| `fleeting` | "记一下……" | 追加到今天的日记 |
| `capture` | 给一个 URL 或文件路径 | 抓取内容，生成资料笔记 |
| `log` | "整理这次对话" | 当前对话 → 结构化笔记 |
| `write` | "写一篇概念卡……" | 明确指定类型写入笔记 |
| `organize` | "整理 RAG 相关的笔记" | 搜索 vault，合并成主题页 |
| `query` | "在我笔记里查……" | 知识库问答，带引用 |
| `lint` | "检查知识库" / "lint" | 健康检查，报告问题 |
| `index` | "重建索引" / "index" | 生成全局导航页 |

写入笔记（capture / write）后还会自动输出**关联建议**，告诉你哪些 MOC 或 Topic 值得添加链接。

---

## 初始化：一行命令建好目录

首次使用前，先让 skill 把 笔记的目录结构建好：

```
/obsidian 初始化
```

执行结果：

```
[OK] Created 8 directories:
  + 00-Inbox/
  + 01-DailyNotes/
  + 02-Projects/
  + 03-Knowledge/Concepts/
  + 03-Knowledge/Literature/
  + 03-Knowledge/MOCs/
  + 03-Knowledge/Topics/
  + 04-Archive/

~/obsidian/
├── 00-Inbox/
├── 01-DailyNotes/
├── 02-Projects/
├── 03-Knowledge/
│   ├── Concepts/
│   ├── Literature/
│   ├── MOCs/
│   └── Topics/
└── 04-Archive/
```

可以重复执行，已存在的目录会自动跳过。

---

## 闪念速记：不打断思路

最高频的需求：想到一个点，立刻记下来，不想打开 Obsidian。

```
记一下，context window 对 RAG 召回率的影响值得专门测一次 #rag #todo
```

执行结果：

```
[OK] Appended to: 01-DailyNotes/2026-04-07.md
```

内容追加到当天日记的 `# Fleeting` 区块，带时间戳：

```markdown
# Fleeting
- 20:31 context window 对 RAG 召回率的影响值得专门测一次 #rag #todo
```

日记文件不存在时自动创建，`# Fleeting` 区块不存在时自动追加。零配置，零打断。

---

## 抓取网页：不再手动整理文章

读到一篇好文章，以前的做法是复制全文、贴进 Obsidian、手动提炼。现在：

```
/obsidian 帮我整理这篇 https://example.com/harness-engineering
```

skill 用 `WebFetch` 抓取页面全文，然后按照资料笔记的结构提取字段：

- **核心观点**：完整论证链，不只是结论
- **方法要点**：具体步骤、数字、阈值、边界情况
- **原文主要内容**：按章节重建，目标是读这篇笔记等于读了原文 80% 的信息量
- **细节**：数据点、引用、令人意外的事实
- **可转化概念**：值得单独建概念卡的名词
- **知识连接**：与已有笔记的关联

写入 `03-Knowledge/Literature/Literature - {标题}.md`，frontmatter 自动填充。

本地文件也支持——给文件路径就行：

```
/obsidian 整理这个 C:/Downloads/paper.md
```

---

## 对话转文档：不让讨论成果白白消失

技术讨论、设计决策、调研梳理——这些对话结束后通常就沉在历史记录里。

```
把这次对话整理成笔记
```

skill 分析当前对话内容，自动判断笔记类型：

- 调研 / 学习某个知识点 → `literature`
- 深度主题讨论 → `topic`
- 项目规划 → `project`
- 概念拆解 → `concept`

选完类型，提取字段，让你确认标题和内容后写入。保留的是具体的决策、数据、推理过程，不是抽象摘要。

---

## 直接写笔记：明确类型，一步到位

有时候不需要 AI 分析对话，你已经知道要写什么——比如看完一篇论文想整理成资料笔记，或者有个概念想单独建一张卡片：

```
帮我写一篇 Transformer 的概念卡
核心机制是 self-attention，解决 RNN 并行训练难、长依赖建模弱的问题
```

skill 根据关键词识别类型，提取字段，写入对应目录：

| 说法 | 类型 | 目录 |
|------|------|------|
| 资料笔记、文章、论文 | `literature` | `03-Knowledge/Literature/` |
| 概念卡、概念 | `concept` | `03-Knowledge/Concepts/` |
| 主题页、主题 | `topic` | `03-Knowledge/Topics/` |
| 项目页、项目 | `project` | `02-Projects/` |

与 `log` 的区别：`log` 是回头整理对话，`write` 是当下明确地写一篇新笔记。

---

## 整理归档：把散乱笔记变成知识结构

收集了一堆相关笔记，但还没形成系统：

```
整理一下我关于 Agent 架构的笔记
```

skill 在 vault 里搜索匹配的笔记文件，列出清单让你确认，然后读取内容，提炼成一篇 `topic` 或 `MOC`：

- 不重复的核心观点汇总
- 共同涉及的概念
- 各笔记之间的链接
- 当前结论 + 未解决问题

Inbox 里积压的临时笔记也会在这个过程中被识别出来，提示你归档到对应目录。

---

## 知识库问答：从 vault 里找答案

积累了几十篇笔记之后，新的问题来了——想不起来某个概念在哪篇笔记里，或者想综合几篇的结论。

```
在我笔记里查一下 Transformer 的局限性有哪些
```

skill 用 Grep 在 vault 的 `03-Knowledge` 和 `02-Projects` 里搜索关键词，读取匹配段落，然后综合回答。关键是每个论点都标注来源：

```
自注意力的计算复杂度是 O(n²)，处理长文本代价高 — [[Concept - Self-Attention]]
实际部署中 KV Cache 是主要内存瓶颈 — [[Literature - LLM Inference Optimization]]
```

vault 里没有相关内容时会直接告知，不会凭空生成。

如果这次回答值得留存，可以说"存下来"，skill 会把它写成一篇新的 `topic` 笔记。

---

## 关联建议：写完自动提示链接

写入笔记之后，脚本会扫描 vault 里的 MOC 和 Topic 文件，找出主题匹配但还没链接到新笔记的文件：

```
[OK] Written: 03-Knowledge/Literature/Literature - Attention Survey.md

[Link suggestions]
  → 03-Knowledge/MOCs/MOC - AI Learning.md  (# 资料  ← add [[Literature - Attention Survey]])
  → 03-Knowledge/Topics/Topic - Transformer.md  (# 重要资料  ← add [[Literature - Attention Survey]])
```

确认后，Claude 直接用 Edit 工具把链接写进对应区块，不需要你手动操作。

这解决了笔记孤立的问题——每篇新笔记写完就进入知识网络，而不是躺在目录里无人问津。

---

## 健康检查：让 vault 不退化

知识库积累到一定规模，会出现各种问题：改了笔记标题忘记更新链接，Inbox 里的草稿一直没整理，某些笔记写了一半就放弃了。

```
/obsidian 检查知识库
```

扫描结果按问题类型分组：

```
[Lint] Scanned 47 notes in ~/obsidian/

[Broken links] (1)
⚠ 03-Knowledge/MOCs/MOC - AI Learning.md → [[Concept - GPT5]]

[Orphan notes] (2)  not referenced from any MOC/Topic
⚠ 03-Knowledge/Concepts/Concept - LoRA.md
⚠ 03-Knowledge/Literature/Literature - RAG Survey.md

[Inbox backlog] (1)  stuck >7 days
⚠ 00-Inbox/Literature - Some Draft.md (11 days old)

[Skeleton notes] (1)  >50% fields empty
⚠ 03-Knowledge/Topics/Topic - Prompt Engineering.md (5/7 sections empty)

[Stale notes] (1)  not updated in 90+ days
⚠ 03-Knowledge/Concepts/Concept - Attention.md (120 days since update)
```

加 `--auto-fix` 可以自动修复 frontmatter 缺失字段（比如没有 `status` 或 `updated`），其余问题报告出来让你决定怎么处理。

---

## 全局索引：知道 vault 里有什么

随着笔记增多，你需要一个入口知道"我有什么"。

```
/obsidian 重建索引
```

在 vault 根目录生成 `_index.md`：

```markdown
# Knowledge Base Index

_Last rebuilt: 2026-04-08_

## Projects (2)
- [[Project - claude-obsidian]] — Claude Code skill for Obsidian (2026-04-08)
- [[Project - Local RAG]] — Build local RAG demo (2026-04-05)

## Topics (3)
- [[Topic - RAG]] — 检索增强生成综合 (2026-04-05)
...

## Recent (last 7 days)
- 2026-04-08: [[Literature - Attention Survey]]
- 2026-04-07: [[Concept - Self-Attention]]
```

不需要手动维护——每次 `write` 或 `capture` 写入新笔记时，脚本自动把条目追加进去。`index` 命令只在需要全量重建时用。

---

## 笔记类型

支持五种结构化类型，每种有固定的目录和字段：

```
00-Inbox/        ← 草稿 / 内容不足的笔记
01-DailyNotes/   ← 闪念追加到这里
02-Projects/     ← 项目页（含实验记录章节）
03-Knowledge/
  Concepts/      ← 概念卡（单个概念的深度拆解）
  Literature/    ← 资料笔记（文章、论文、博客）
  MOCs/          ← 导航地图
  Topics/        ← 主题页（多篇笔记的综合）
04-Archive/      ← 归档笔记
```

内容不足时自动路由到 Inbox。比如 `literature` 类型的必填字段是 `核心观点` 和 `方法要点`，两者都空就进 Inbox，并告知你缺哪些字段。

---

## 安装

```bash
git clone https://github.com/your-username/claude-obsidian.git
cd claude-obsidian
python install.py
```

安装脚本把 skill 和脚本复制到 `~/.claude/` 对应目录，之后在任何 Claude Code 会话里输入 `/obsidian` 即可使用。

默认 vault 路径是 `~/obsidian`，用环境变量覆盖：

```bash
export OBSIDIAN_VAULT_PATH=/path/to/your/vault
```

**依赖：** Python 3.9+、Claude Code

---

## 底层结构

两层分工，职责清晰：

```
SKILL.md              — 意图识别、字段提取（Claude 执行）
    ↓
obsidian_writer.py    — 模板渲染、文件写入（Python 脚本，无 LLM 调用）
```

脚本可以独立运行，方便调试和自动化：

```bash
# 预演模式，只输出内容不写文件
python skills/obsidian/obsidian_writer.py \
  --type literature \
  --title "测试" \
  --fields '{"核心观点": "..."}' \
  --dry-run
```

80 个单元测试覆盖所有笔记类型、闪念追加逻辑、草稿路由、文件名冲突处理、lint 检查、关联建议和索引生成。

---

## 项目地址

GitHub: https://github.com/your-username/claude-obsidian

中文文档见 `README-CN.md`。
