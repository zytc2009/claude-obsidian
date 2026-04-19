# Capture Adapter & Relation Extraction Design

**Date:** 2026-04-19
**Status:** Implemented
**Scope:** 多平台内容采集适配器 + LLM 关系提取 → wikilinks

---

## 1. Background

来源：SparkNoteAI（开源）的两个模块：
- `apps/backend/app/services/importers/` — 微信/小红书爬虫，httpx + BeautifulSoup，与业务层低耦合
- `apps/backend/app/services/knowledge_graph.py` — LLM 概念提取 + 关系发现，prompt 和 JSON 解析逻辑可复用，DB 层需丢弃

### 1.1 现有 capture 模式的局限

`obsidian_writer.py --mode capture` 目前只支持普通 HTTP URL，依赖 Claude Code 读取网页内容后传入。微信公众号文章需要特定的 header 和 DOM 选择器，小红书需要从 SSR JSON 提取数据，通用抓取无法处理。

### 1.2 现有知识关联的局限

`memory_manager.py` 用关键词激活模型推断关系，精度依赖词频，无法理解"RAG 是一种检索增强技术，属于 LLM 应用层"这类语义关系。新笔记写入后，相关笔记的 wikilinks 需要手动添加。

---

## 2. Feature 1：多平台采集适配器

### 2.1 目标

`/obsidian capture <URL>` 自动识别平台，调用对应适配器，产出与现有 `literature` 笔记相同格式的内容。

支持平台：
- 微信公众号（`mp.weixin.qq.com`）
- 小红书（`www.xiaohongshu.com` / `xhslink.com`）
- 普通网页（fallback，现有逻辑）

### 2.2 文件结构

```
skills/obsidian/
└── importers/
    ├── __init__.py
    ├── base.py          # ImportResult dataclass + BaseImporter ABC
    ├── wechat.py        # 从 SparkNoteAI 移植，去掉 logger/image_cache
    ├── xiaohongshu.py   # 从 SparkNoteAI 移植，去掉 logger/image_cache
    └── router.py        # URL → importer 路由 + asyncio.run() 入口
```

### 2.3 ImportResult → literature 字段映射

```
ImportResult.title      → title
ImportResult.content    → 核心观点 + 方法要点（LLM 在 SKILL.md 层提取）
ImportResult.summary    → 一句话摘要
ImportResult.platform   → source frontmatter 字段
ImportResult.source_url → source frontmatter 字段
ImportResult.metadata   → author / tags 等额外 frontmatter 字段
```

`capture` 模式的流程不变——Python 脚本负责抓取和解析，SKILL.md 层的 Claude 负责从原文提取"核心观点"和"方法要点"，最终调用 `write_note()` 写成 `literature` 笔记。

### 2.4 router.py 接口

```python
def detect_platform(url: str) -> str:
    """返回 'wechat' | 'xiaohongshu' | 'generic'"""

def fetch_url(url: str) -> ImportResult:
    """同步入口，内部用 asyncio.run() 调用异步 importer。"""
```

CLI：
```bash
python importers/router.py --url "https://mp.weixin.qq.com/s/xxx"
# 输出 JSON：{"title": "...", "content": "...", "platform": "wechat", ...}
```

### 2.5 移植改动

从 SparkNoteAI 移植时的必要修改：

| 原代码 | 移植后 |
|--------|--------|
| `from app.core.logger import get_logger` | `import logging; logger = logging.getLogger(__name__)` |
| `image_cache_service` 参数 | 移除，图片保留原始 URL |
| `async def import_from_url()` | 保留 async，由 `router.py` 的 `asyncio.run()` 驱动 |

### 2.6 新依赖

```
httpx >= 0.27
beautifulsoup4 >= 4.12
```

需加入 `pyproject.toml` 的 optional extras 或直接 dependencies。

---

## 3. Feature 2：LLM 关系提取 → Wikilinks

### 3.1 目标

写入新笔记后，自动提取笔记中的核心概念，与 vault 现有笔记做匹配，将匹配到的笔记添加为 wikilinks，追加到笔记的 `## 相关概念` section。

### 3.2 文件

```
skills/obsidian/
└── relation_extractor.py   # 新建，独立模块
```

### 3.3 核心函数

```python
def extract_concepts(title: str, content: str) -> list[dict]:
    """
    调用 Anthropic API，返回概念列表。
    每项：{"name": "...", "type": "concept|topic|entity", "description": "..."}
    需要环境变量 ANTHROPIC_API_KEY。
    """

def match_to_vault(concepts: list[dict], vault: Path) -> list[str]:
    """
    将概念名与 vault 全量 note stems 做模糊匹配。
    匹配策略：
      1. 精确匹配（大小写不敏感）
      2. 归一化匹配（去标点、合并空格）
      3. 包含关系（概念名 ⊂ stem 或 stem ⊂ 概念名，仅 stem 长度 ≤ 20）
    返回 ["[[Concept - RAG]]", "[[Topic - LLM应用]]"] 格式。
    """

def append_related_concepts(note_path: Path, wikilinks: list[str]) -> None:
    """
    在笔记末尾追加或更新 ## 相关概念 section。
    已存在的 section：增量追加，不覆盖。
    """

def extract_and_link(vault: Path, note_path: Path) -> list[str]:
    """主入口：读取笔记 → 提取概念 → 匹配 → 写回。返回添加的 wikilinks 列表。"""
```

### 3.4 Prompt 设计（来自 SparkNoteAI）

**概念提取 prompt：**
```
system: 你是一个专业的知识图谱构建助手。从笔记中提取 3-10 个核心概念。
        判断类型：concept（核心概念）/ topic（主题类别）/ entity（人物/组织/工具）。
        返回严格 JSON 格式。

user: 笔记标题：{title}
      笔记内容：{truncated_content}

      返回格式：
      {"concepts": [{"name": "...", "type": "...", "description": "..."}]}
```

**JSON 解析（来自 SparkNoteAI `_extract_json_from_response`）：**
- 处理 markdown 代码块包裹
- 处理 LLM 返回前缀文字
- 括号深度匹配兜底

### 3.5 触发时机

在 `write_note()` 成功写入后，与 memory update 并列调用：

```python
# 现有
mm.extract_and_upsert(...)

# 新增
if relation_extractor is not None:
    try:
        links = relation_extractor.extract_and_link(vault, filepath)
        if links:
            logger.info(f"Added {len(links)} related concept links")
    except Exception as _rel_err:
        warnings.warn(f"Relation extraction failed (non-fatal): {_rel_err}")
```

**触发条件：**
- 非草稿
- note_type 在 `{"literature", "concept", "topic", "project"}` 中
- 环境变量 `ANTHROPIC_API_KEY` 存在
- 环境变量 `OBSIDIAN_RELATION_EXTRACT=1`（可关闭，默认关）

`OBSIDIAN_RELATION_EXTRACT` 默认关闭的原因：每次写笔记都调用 API 有成本，用户应主动开启。

### 3.6 content 截断策略（来自 SparkNoteAI）

移植 `truncate_content_smart()`：
- 按段落分割
- 保留首尾段落
- 中间段落按长度降序填充
- 上限 1500 tokens（中文约 1000 字）

### 3.7 LLM 调用

使用同步 Anthropic SDK（与 obsidian_writer.py 的同步风格一致）：

```python
import anthropic

client = anthropic.Anthropic()  # 读取 ANTHROPIC_API_KEY
message = client.messages.create(
    model="claude-haiku-4-5-20251001",   # 低成本，关系提取不需要最强模型
    max_tokens=1024,
    system=system_prompt,
    messages=[{"role": "user", "content": prompt}],
)
return message.content[0].text
```

---

## 4. Data Flow

```
用户：/obsidian capture https://mp.weixin.qq.com/s/xxx
        ↓
SKILL.md 检测到微信 URL
        ↓
router.py fetch_url() → WechatImporter → ImportResult
        ↓
SKILL.md Claude 提取核心观点/方法要点
        ↓
obsidian_writer.py write_note(type=literature) → 03-Knowledge/Literature/
        ↓
relation_extractor.extract_and_link()
  → Anthropic API 提取概念
  → match_to_vault() 匹配现有笔记
  → append_related_concepts() 追加 ## 相关概念
        ↓
memory_manager.extract_and_upsert()
```

---

## 5. File Changes

| 文件 | 变更 |
|------|------|
| `skills/obsidian/importers/__init__.py` | 新建 |
| `skills/obsidian/importers/base.py` | 新建（移植）|
| `skills/obsidian/importers/wechat.py` | 新建（移植）|
| `skills/obsidian/importers/xiaohongshu.py` | 新建（移植）|
| `skills/obsidian/importers/router.py` | 新建 |
| `skills/obsidian/relation_extractor.py` | 新建 |
| `skills/obsidian/obsidian_writer.py` | 修改：relation_extractor 集成 |
| `skills/obsidian/SKILL.md` | 修改：capture 命令说明 + 平台识别 |
| `pyproject.toml` / `requirements` | 新增 httpx, beautifulsoup4, anthropic |
| `tests/test_importers.py` | 新建 |
| `tests/test_relation_extractor.py` | 新建 |

---

## 6. Open Questions

- **Q1:** 小红书的 SSR 结构经常变，是否需要版本检测机制？
  - 建议：现在不做，等实际使用中发现结构变化再加。
- **Q2:** relation_extractor 的 API 成本控制？
  - 使用 Haiku 模型，每次调用约 $0.001，100 篇笔记约 $0.1，可接受。
- **Q3:** `match_to_vault` 的误匹配率？
  - 精确匹配优先，包含匹配只对长度 ≤ 20 的 stem 生效，误匹配风险低。
