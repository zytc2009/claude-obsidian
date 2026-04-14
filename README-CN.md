# claude-obsidian

在 Claude Code 会话中直接向本地 Obsidian 知识库写入结构化笔记，无需复制粘贴，无需手动排版。

## 概述

`claude-obsidian` 连接 Claude Code 会话与 Obsidian。你可以用自然语言或 `/obsidian` 命令捕捉零散想法、归档网页文章、将对话整理成笔记、将相关笔记合并为主题摘要、查询知识库、保持 vault 健康。

**架构：**
```
Claude Code Skill (SKILL.md)      - 意图识别，字段提取
        ↓
obsidian_writer.py                - 模板渲染，文件读写（无 LLM 调用）
        ↓
你的 Obsidian Vault
  ├── 00-Inbox/                   ← 草稿 / 不完整笔记
  ├── 01-DailyNotes/              ← 闪念追加到此处
  ├── 02-Projects/                ← 项目页
  ├── 03-Knowledge/
  │   ├── Concepts/               ← 概念卡
  │   ├── Literature/             ← 资料笔记
  │   ├── MOCs/                   ← 导航地图
  │   └── Topics/                 ← 主题页
  └── 04-Archive/                 ← 已归档笔记
```

## 操作模式

### `fleeting` - 闪念速记

一步将带时间戳的想法追加到当天的日记。

```
记一下，可以用 MOC 来组织跨主题的笔记链接
想到一个 #rag context window 对 recall@5 的影响值得测一下
```

内容追加到 `01-DailyNotes/YYYY-MM-DD.md` 的 `# Fleeting` 区块。文件不存在时自动创建。

### `capture` - 抓取网页或文件

抓取网页或读取本地文件，生成密集的 `literature` 笔记，保留原文约 80% 的信息量。

```
/obsidian capture https://example.com/article
/obsidian capture C:/Downloads/paper.md
```

### `log` - 对话转文档

分析当前对话，写入结构化笔记。类型自动判断：

| 对话内容 | 笔记类型 |
|---------|---------|
| 调研 / 学习某个知识点 | `literature` |
| 围绕某主题的深度讨论 | `topic` |
| 项目规划 | `project` |
| 具体概念拆解 | `concept` |

```
/obsidian log this conversation
```

### `write` - 创建结构化笔记

明确指定类型写入笔记：

| 说法 | 类型 |
|------|------|
| 资料笔记、文章、论文、博客 | `literature` |
| 概念卡、概念 | `concept` |
| 主题页、主题 | `topic` |
| 项目页、项目 | `project` |

### `organize` - 搜索、合并、归档

在 vault 中搜索相关笔记，合并成 `topic` 或 `MOC`，并提示整理 Inbox 中待归档的笔记。

```
/obsidian organize RAG
```

### 主题发现

写入新笔记后，脚本会输出：

- `[Link suggestions]`：优先推荐现有 `topic`，其次推荐 `MOC`
- 可解释的推荐原因，例如 `strength=high`、`title=...`、`body=...`
- `[Topic suggestion]`：当找不到足够强的现有主题匹配时，保守提示你考虑新建一个 `topic`

这个功能的重点是帮助你判断一篇新笔记应该归到哪里，而不是激进地自动加满链接。

### `query` - 知识库问答

搜索已有笔记回答问题，每个论点附引用来源。可选将回答归档为新的主题笔记。

```
/obsidian query what do my notes say about RAG?
在我笔记里查一下 Transformer 的局限性
```

检索分两层：

- **第一层（默认）：** 仅扫描 `topic` 笔记，从 `主题说明`、`当前结论`、`未解决问题` 字段组织回答，每个论点附来源引用。
- **第二层（按需）：** 无 topic 匹配时，或你说"展开"/"细节"时，返回按所属 topic 分组的 literature / project 笔记命中。没有 topic 父节点的孤儿命中单独列出，让碎片化在每次查询时可见。

回答中每个论点标注来源：`答案内容 - [[Concept - Self-Attention]]`。

### `lint` - 知识库健康检查

扫描 vault，报告质量问题，可选自动修复简单问题。

```
/obsidian lint
/obsidian lint --auto-fix
```

| 检查项 | 说明 | 处理方式 |
|-------|------|--------|
| 断链 | `[[wikilinks]]` 指向不存在的笔记 | 报告 |
| 孤立笔记 | Knowledge/Projects 下未被任何 MOC/Topic 引用的文件 | 报告 |
| Inbox 积压 | `00-Inbox` 中超过 7 天的笔记 | 报告 |
| 空壳笔记 | 超过 50% 字段仍是 `_placeholder_` | 报告 |
| 陈旧笔记 | 活跃笔记 90 天以上未更新 | 报告 |
| 综述滞后 | Topic 笔记的 linked literature 在 topic 最后更新 30 天后仍有新增 | 报告 |
| 缺失 frontmatter | 缺少 `status`/`created`/`updated` | 加 `--auto-fix` 自动修复 |

检测到的问题会追加到 `_corrections.jsonl` 中（`resolved: false`），作为机器可读的修正事件流。

示例输出：
```
[Lint] Scanned 47 notes in D:/obsidian/

[Broken links] (1)
⚠ 03-Knowledge/MOCs/MOC - AI Learning.md → [[Concept - GPT5]]

[Orphan notes] (2)
⚠ 03-Knowledge/Concepts/Concept - LoRA.md
⚠ 03-Knowledge/Literature/Literature - RAG Survey.md

[Inbox backlog] (1)
⚠ 00-Inbox/Literature - Some Draft.md (11 days old)
```

### `topic-scout` - 聚类孤儿笔记，推荐 topic

扫描 `00-Inbox/` 和 `03-Knowledge/` 中没有 topic 父节点的笔记，按共享词汇聚类，提出 topic 建议候选。

```
/obsidian topic-scout
```

示例输出：

```
[Topic Scout] Scanned 6 orphan note(s)

Found 2 cluster(s) — consider creating a topic for each:

Cluster 1 (3 notes) → suggested: Topic - Harness Engineering
  [[Literature - Harness Engineering 最佳实践]]
  [[Literature - Harness Engineering与Agents编排]]
  [[Literature - 一文读懂Harness Engineering]]

Singletons (1 note(s) with no close match):
  [[Literature - RAG Survey 2024]]
```

你选择哪些聚类要落地为 topic 笔记。按需运行，不自动执行。

### `index` - 重建知识库索引

重建 vault 根目录下的 `_index.md`，作为全局导航页，按分类列出所有笔记及摘要和日期。每次 `write` 或 `capture` 后，新笔记会自动加入索引。

```
/obsidian index
```

### `init` - 初始化目录结构

首次使用时创建所有必要目录，完成后输出目录树确认。可重复执行，已存在的目录会自动跳过。

```
/obsidian init
```

示例输出：

```
[OK] Created 8 directories:
  + 00-Inbox/
  + 01-DailyNotes/
  ...

D:/obsidian/
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

## 可观测性

vault 根目录维护两个机器可读事件流：

| 文件 | 用途 |
|------|------|
| `_corrections.jsonl` | `lint` 发现的质量问题——断链、孤立笔记、综述滞后等。每行：`{ts, note, issue_type, detail, detected_by, resolved}` |
| `_events.jsonl` | 显式推荐反馈（reject / modify-accept）。每行：`{ts, event_type, suggestion_type, source_note, target_notes, action, reason}` |

`_log.md` 是人可读的操作日志。超过 500 条后，旧条目自动轮转到 `_log.archive.md`。

链接推荐会读取 `_events.jsonl`，对同一 source note 下被拒绝过的 target 进行降权。词法匹配仍是主要排名信号。

## 笔记类型

### Literature - 文章 / 论文笔记

密集型笔记，目标是让你在几周后无需重读原文，也能回忆起约 80% 的信息。

关键字段：`core ideas`（完整论证链，包含 why 和 how）、`method details`（步骤、数字、阈值、例子）、`main content`（按章节重建）、`details`（数据点、引用、令人意外的事实）、`concepts to extract`、`knowledge links`

### Concept - 概念卡

每个概念独立一页，从资料或讨论中提炼。

关键字段：`one-line definition`、`core mechanism`、`advantages`、`limitations`、`use cases`、`common misconceptions`

### Topic - 主题摘要

用于整合你当前对某个主题的理解，把 `literature` 和 `project` 笔记中的结论汇总到一个页面。

关键字段：`topic description`、`core question`、`current conclusions`、`key references`、`related projects`、`open questions`

### Project - 问题与解法记录

轻量记录实际工作中的问题、排查过程与解决方案。

关键字段：`project description`、`root cause analysis`、`investigation process`、`solution`、`validation`、`risks and open issues`

## 草稿路由

以下情况会自动写入 `00-Inbox/`：

- 你明确说了 “draft” 或 “save to inbox”
- 必填字段有一半以上无法填写

各类型必填字段如下：

| 类型 | 必填字段 |
|------|---------|
| `literature` | core ideas, method details |
| `concept` | one-line definition, core mechanism |
| `topic` | topic description, current conclusions |
| `project` | project description, investigation process, solution |

## 安装

```bash
git clone https://github.com/your-username/claude-obsidian.git
cd claude-obsidian
python install.py
```

安装脚本会将 `skills/obsidian/obsidian_writer.py` 复制到 `~/.claude/scripts/`，并将 `skills/obsidian/` 复制到 `~/.claude/skills/obsidian/`。

**配置 vault 路径**（默认：`~/obsidian/`）：

```bash
# 方式一：环境变量
export OBSIDIAN_VAULT_PATH=/path/to/your/vault

# 方式二：调用时传 --vault
python obsidian_writer.py --vault /path/to/vault ...
```

**依赖：** Python 3.9+，Claude Code

## 脚本参考

`obsidian_writer.py` 是一个独立 CLI，不依赖 LLM，适合在 Claude Code 之外测试或脚本化调用。

```bash
# 写入一篇笔记
python skills/obsidian/obsidian_writer.py \
  --type literature \
  --title "Attention Is All You Need" \
  --fields '{"核心观点": "...", "方法要点": "..."}' \
  --draft false

# 追加一条闪念
python skills/obsidian/obsidian_writer.py \
  --type fleeting \
  --fields '{"content": "interesting idea", "tags": "#ai"}'

# 初始化 vault 目录
python skills/obsidian/obsidian_writer.py --type init

# 知识库健康检查
python skills/obsidian/obsidian_writer.py --type lint

# 健康检查并自动修复 frontmatter
python skills/obsidian/obsidian_writer.py --type lint --auto-fix

# 重建全局索引 (_index.md)
python skills/obsidian/obsidian_writer.py --type index

# 预演：只预览不写入
python skills/obsidian/obsidian_writer.py --type topic --title "RAG" \
  --fields '{}' --dry-run
```

## 开发

```bash
# 运行测试
python -m pytest

# 带覆盖率运行
python -m pytest --cov=scripts
```

测试覆盖所有笔记类型、闪念追加逻辑、草稿路由、文件名冲突处理、lint 检查、链接建议、索引生成、可观测性事件流、孤儿追踪、topic-scout 聚类、综述滞后检测和 CLI（137 个测试）。

## 文件命名

所有笔记遵循 `{Prefix} - {Title}.md`。如果同名文件已存在，会自动追加当天日期，例如：`Literature - Title 2026-04-07.md`。
