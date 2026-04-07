# Claude Code → Obsidian 自动化工作流 — Design Spec

**Date:** 2026-04-07  
**Status:** Approved  
**Scope:** Claude Code skill + Python script，与 harness-runtime 无关

---

## 1. 目标

在 Claude Code 会话中，通过斜杠命令或自然语言，将调研内容、实验记录、主题汇总、项目规划直接写入本地 Obsidian vault（`D:/whb/obsidian/`），无需手动复制粘贴或在 Obsidian 内切换。

**不在范围内：**
- 会话结束自动触发（Stop hook）
- harness-runtime 集成
- Obsidian 插件（Claudian 等）
- 概念卡（Concept）和日记（Daily Note）模板

---

## 2. 整体架构

```
用户（自然语言 or 斜杠命令）
  ↓
Claude Code Skill: obsidian
  - 意图识别（笔记类型）
  - 内容结构化（字段提取）
  - 写入路由决策（Inbox or 目标目录）
  - 调用 Python 脚本
  ↓
~/.claude/scripts/obsidian_writer.py
  - 接收 JSON 参数
  - 渲染模板（frontmatter + 正文）
  - 生成文件名
  - 写入文件
  ↓
D:/whb/obsidian/
  ├── 00-Inbox/           ← draft 笔记
  ├── 03-Knowledge/
  │   ├── Literature/     ← 资料笔记
  │   ├── Experiments/    ← 实验记录
  │   └── Topics/         ← 主题页
  └── 02-Projects/        ← 项目页
```

**职责边界：**
- Skill：语言理解，内容提取 → 输出结构化 JSON
- Script：文件操作，模板渲染 → 无 LLM 调用，可独立测试

---

## 3. 文件位置

| 文件 | 路径 |
|------|------|
| Skill | `~/.claude/skills/obsidian` |
| Script | `~/.claude/scripts/obsidian_writer.py` |
| Obsidian vault | `D:/whb/obsidian/` |

---

## 4. 调用接口

### 斜杠命令
```
/obsidian <type> [draft] [content]
```

示例：
```
/obsidian literature https://arxiv.org/abs/1706.03762
/obsidian literature draft          # 草稿，进 Inbox
/obsidian experiment                # 从当前对话提取
/obsidian topic RAG
/obsidian project "本地知识库搭建"
```

### 自然语言（Skill 识别以下模式）
```
"帮我写一个关于 X 的资料笔记"  → type: literature
"把这次实验记录下来"            → type: experiment
"建一个 X 主题页"               → type: topic
"新建一个 X 项目页"             → type: project
```

### Script 调用约定
```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type <literature|experiment|topic|project> \
  --title "<笔记标题>" \
  --fields '<JSON 字符串>' \
  --draft <true|false>
```

Script 标准输出（Skill 转发给用户）：
```
✓ 已写入：03-Knowledge/Literature/Literature - Attention Is All You Need.md
```

---

## 5. 支持的笔记类型

### 5.1 Literature（资料笔记）
- 目标目录：`03-Knowledge/Literature/`
- 文件名：`Literature - {title}.md`
- 必填字段：title, source, 详细的内容，核心观点, 方法要点
- 可选字段：author, 存疑之处, 可转化概念

### 5.2 Experiment（实验记录）
- 目标目录：`03-Knowledge/Experiments/`
- 文件名：`Experiment - {title}.md`
- 必填字段：实验目标, 实验环境, 执行步骤, 结论
- 可选字段：实验设计, 下次改进

### 5.3 Topic（主题页）
- 目标目录：`03-Knowledge/Topics/`
- 文件名：`Topic - {title}.md`
- 必填字段：主题说明, 核心概念
- 可选字段：当前结论, 下一步路线

### 5.4 Project（项目页）
- 目标目录：`02-Projects/`
- 文件名：`Project - {title}.md`
- 必填字段：项目目标, 完成标准, 任务拆分
- 可选字段：风险, 产出

---

## 6. 内容提取规则

### 输入：主题名
- Claude 从对话上下文 + 自身知识生成字段内容
- 生成内容标注为推测，建议用户补充

### 输入：原始内容（URL / 粘贴文本 / 代码结果）
- Claude 按模板字段逐一提取
- 无法提取的字段写入 `_待补充_`，不瞎填

---

## 7. 写入路由

| 条件 | 目标路径 |
|------|---------|
| 用户显式指定 `draft` | `00-Inbox/` |
| Claude 判断内容不完整（必填字段中超过半数为空） | `00-Inbox/`，并告知用户哪些字段需要补充 |
| 内容完整，无 draft 标志 | 对应目标目录 |

---

## 8. 模板渲染规则（Script 执行）

- `created` / `updated` 由 Script 注入当前日期（`YYYY-MM-DD`），不依赖 Templater
- 空字段写入 `_待补充_`，保持模板结构完整
- 写入前检查同名文件：若存在，追加日期后缀（`Literature - X 2026-04-07.md`）
- 目标目录不存在时自动创建

---

## 9. 错误处理

| 场景 | 处理方式 |
|------|---------|
| 无法识别笔记类型 | Skill 询问："你想创建哪种笔记？literature / experiment / topic / project" |
| 内容不足，大量字段为空 | 自动加 draft，写入 Inbox，提示需补充的字段 |
| 同名文件已存在 | 追加日期后缀，不覆盖 |
| 目标目录不存在 | Script 自动创建 |
| Script 执行失败 | Skill 捕获 stderr，展示错误原因 |

---

## 10. 测试策略

### Script 独立测试（无需 Claude）
```bash
# dry-run：只打印内容和路径，不写文件
python obsidian_writer.py --type literature --title "Test" \
  --fields '{"核心观点": "test"}' --draft true --dry-run
```

### Skill 手动验收（3 个核心场景）
1. 给 URL → 生成 literature 笔记，写入 `Literature/`
2. 指定 `draft` → 写入 `Inbox/`
3. 只给主题名 → 生成内容，空字段有 `_待补充_` 占位符
