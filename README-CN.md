# claude-obsidian

在 Claude Code 会话中直接向本地 Obsidian 知识库写入结构化笔记——无需复制粘贴，无需手动排版。

## 概述

`claude-obsidian` 连接 Claude Code 会话与 Obsidian。你可以用自然语言或 `/obsidian` 命令捕捉零散想法、归档网页文章、将对话整理成笔记、将相关笔记合并为主题摘要、查询知识库、保持 vault 健康。

**架构：**
```
Claude Code Skill (SKILL.md)      — 意图识别，字段提取
        ↓
obsidian_writer.py                — 模板渲染，文件读写（无 LLM 调用）
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

### `fleeting` — 闪念速记

一步将带时间戳的想法追加到当天的日记。

```
记一下，可以用 MOC 来组织跨主题的笔记链接
想到一个 #rag context window 对召回率的影响值得测一下
```

内容追加到 `01-DailyNotes/YYYY-MM-DD.md` 的 `# Fleeting` 区块。文件不存在时自动创建。

### `capture` — 抓取网页或文件

抓取网页或读取本地文件，生成密集的 `literature` 笔记，保留原文约 80% 的信息量。

```
/obsidian 抓取这篇文章 https://example.com/article
/obsidian 整理这个文件 C:/Downloads/paper.md
```

### `log` — 对话转文档

分析当前对话，写入结构化笔记。类型自动判断：

| 对话内容 | 笔记类型 |
|---------|---------|
| 调研 / 学习某个知识点 | `literature` |
| 围绕某主题的深度讨论 | `topic` |
| 项目规划 | `project` |
| 具体概念拆解 | `concept` |

```
把这次对话整理成笔记
```

### `write` — 创建结构化笔记

明确指定类型写入笔记：

| 说法 | 类型 |
|------|------|
| 资料笔记、文章、论文、博客 | `literature` |
| 概念卡、概念 | `concept` |
| 主题页、主题 | `topic` |
| 项目页、项目 | `project` |

### `organize` — 搜索、合并、归档

在 vault 中搜索相关笔记，合并成 `topic` 或 `MOC`，并提示整理 Inbox 中待归档的笔记。

```
整理一下 RAG 相关的笔记
```

### `query` — 知识库问答

搜索已有笔记回答问题，每个论点附引用来源。可选将回答归档为新的主题笔记。

```
在我笔记里查一下 Transformer 的局限性
/obsidian query RAG 召回率的影响因素
```

回答中每个论点标注来源：`答案内容 — [[Concept - Self-Attention]]`

### `lint` — 知识库健康检查

扫描 vault，报告质量问题，可选自动修复简单问题。

```
/obsidian 检查知识库
/obsidian lint
python obsidian_writer.py --type lint --auto-fix
```

| 检查项 | 说明 | 处理方式 |
|--------|------|---------|
| 断链 | `[[wikilink]]` 指向不存在的笔记 | 报告 |
| 孤立笔记 | Knowledge/Projects 下未被任何笔记引用的文件 | 报告 |
| Inbox 积压 | 00-Inbox 中超过 7 天的笔记 | 报告 |
| 空壳笔记 | `_待补充_` 占比超过 50% | 报告 |
| 陈旧笔记 | status=active 且 90 天未更新 | 报告 |
| 缺失 frontmatter | 缺少 status/created/updated 字段 | 加 `--auto-fix` 自动修复 |

示例输出：
```
[Lint] Scanned 47 notes in D:/obsidian/

[Broken links] (1)
⚠ 03-Knowledge/MOCs/MOC - AI Learning.md → [[Concept - GPT5]]

[Orphan notes] (2)
⚠ 03-Knowledge/Concepts/Concept - LoRA.md

[Inbox backlog] (1)
⚠ 00-Inbox/Literature - Some Draft.md (11 days old)
```

### `index` — 重建知识库索引

在 vault 根目录生成/重建 `_index.md`，作为全局导航页，按分类列出所有笔记。每次 `write` 或 `capture` 后自动增量更新，无需手动触发。

```
/obsidian 重建索引
/obsidian index
```

### `init` — 初始化目录结构

首次使用时创建所有必要目录，完成后输出目录树确认。可重复执行，已存在的目录会自动跳过。

```
/obsidian 初始化
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

## 笔记类型说明

### 资料笔记（Literature）

密集型笔记，目标是让你在数周后重读时，无需回看原文即可获取约 80% 的信息量。

核心字段：`核心观点`（完整论证链）、`方法要点`（步骤、数字、例子）、`原文主要内容`（按章节重建）、`细节`（数据点、引用）、`可转化概念`、`知识连接`

### 概念卡（Concept）

每个概念独立一页，从资料或讨论中提炼。

核心字段：`一句话定义`、`核心机制`、`优点`、`局限`、`适用场景`、`常见误区`

### 主题页（Topic）

围绕某个主题，汇聚概念、资料和未解决问题的综合页面。

### 项目页（Project）

项目跟踪，包含目标、任务、风险，以及内嵌的实验记录章节。

## 草稿路由规则

以下情况笔记自动路由至 `00-Inbox/`：

- 你明确说"草稿"或"先放 Inbox"
- 必填字段中超过一半无法填充

各类型必填字段：

| 类型 | 必填字段 |
|------|---------|
| `literature` | `核心观点`、`方法要点` |
| `concept` | `一句话定义`、`核心机制` |
| `topic` | `主题说明`、`核心概念` |
| `project` | `项目目标`、`完成标准`、`任务拆分` |

## 安装

```bash
git clone https://github.com/your-username/claude-obsidian.git
cd claude-obsidian
python install.py
```

安装脚本将 `skills/obsidian/obsidian_writer.py` 复制到 `~/.claude/scripts/`，将 `skills/obsidian/` 复制到 `~/.claude/skills/obsidian/`。

**配置 vault 路径**（默认：`./obsidian`）：

```bash
# 方式一：环境变量
export OBSIDIAN_VAULT_PATH=/path/to/your/vault

# 方式二：调用时传参
python obsidian_writer.py --vault /path/to/vault ...
```

**依赖：** Python 3.9+、Claude Code

## 脚本命令参考

`obsidian_writer.py` 是独立的命令行工具，不依赖 LLM，可在 Claude Code 之外单独使用。

```bash
# 写入笔记
python skills/obsidian/obsidian_writer.py \
  --type literature \
  --title "Attention Is All You Need" \
  --fields '{"核心观点": "...", "方法要点": "..."}' \
  --draft false

# 追加闪念
python skills/obsidian/obsidian_writer.py \
  --type fleeting \
  --fields '{"content": "一个有趣的想法", "tags": "#ai"}'

# 初始化 vault 目录（首次使用）
python skills/obsidian/obsidian_writer.py --type init

# 知识库健康检查（仅报告）
python skills/obsidian/obsidian_writer.py --type lint

# 健康检查 + 自动修复缺失的 frontmatter 字段
python skills/obsidian/obsidian_writer.py --type lint --auto-fix

# 重建全局索引（_index.md）
python skills/obsidian/obsidian_writer.py --type index

# 预演模式：只预览内容，不写入文件
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

测试套件覆盖所有笔记类型、闪念追加逻辑、草稿路由、文件名冲突处理、lint 检查、关联建议、索引生成和命令行接口（共 80 个测试）。

## 文件命名规则

所有笔记均以 `{前缀} - {标题}.md` 命名。若同名文件已存在，自动追加日期后缀，例如：`Literature - 标题 2026-04-07.md`。
