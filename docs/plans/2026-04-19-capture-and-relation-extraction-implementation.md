# Capture Adapter & Relation Extraction Implementation Plan

**Date:** 2026-04-19
**Status:** Completed
**Scope:** 实现多平台采集适配器和 LLM 关系提取，参见 [设计文档](../specs/2026-04-19-capture-and-relation-extraction-design.md)

---

## Repo Context

- 主文件：`skills/obsidian/obsidian_writer.py`
- 记忆系统：`skills/obsidian/memory_manager.py`
- 档案管理：`skills/obsidian/profile_manager.py`
- 测试：`tests/`，运行：`python -m pytest tests/ -q`
- 来源参考：`D:/AI/SparkNoteAI/apps/backend/app/services/importers/`
- 来源参考：`D:/AI/SparkNoteAI/apps/backend/app/services/knowledge_graph.py`

---

## Phase A：多平台采集适配器（Tasks 1-4）

### Task 1 — 新建 `skills/obsidian/importers/` 包

**文件：**
- `skills/obsidian/importers/__init__.py`（空文件）
- `skills/obsidian/importers/base.py`（新建）

`base.py` 内容从 `D:/AI/SparkNoteAI/apps/backend/app/services/importers/base.py` 移植，改动：
1. 删除 `from app.core.logger import get_logger` 及相关 logger 调用
2. 保持其余代码不变（`ImportResult` dataclass + `BaseImporter` ABC）

退出条件：
- `from importers.base import ImportResult, BaseImporter` 可正常导入
- `ImportResult` 包含 `title, content, summary, platform, source_url, metadata` 字段

---

### Task 2 — 移植 `wechat.py` 和 `xiaohongshu.py`

**文件：**
- `skills/obsidian/importers/wechat.py`（新建）
- `skills/obsidian/importers/xiaohongshu.py`（新建）

从 SparkNoteAI 移植，统一改动：
1. `from app.core.logger import get_logger` → `import logging; logger = logging.getLogger(__name__)`
2. `get_logger(__name__)` → `logging.getLogger(__name__)`
3. 删除 `__init__` 中的 `image_cache_service` 参数（直接删除，图片保留原始 URL）
4. 删除 `cache_images_in_content()` 方法（整个方法删除）
5. 其余代码（`fetch_content`、`parse_content`、`_extract_*` 系列方法）保持不变

退出条件：
- `WechatImporter` 和 `XiaohongshuImporter` 可正常实例化
- `WechatImporter().fetch_content` 是 async 方法

---

### Task 3 — 新建 `skills/obsidian/importers/router.py`

**文件：** `skills/obsidian/importers/router.py`（新建）

```python
"""URL 平台检测 + 同步入口封装"""

import asyncio
import json
import sys
from pathlib import Path

from .base import ImportResult
from .wechat import WechatImporter
from .xiaohongshu import XiaohongshuImporter


_PLATFORM_RULES = [
    ("wechat", ["mp.weixin.qq.com"]),
    ("xiaohongshu", ["www.xiaohongshu.com", "xhslink.com"]),
]


def detect_platform(url: str) -> str:
    """返回 'wechat' | 'xiaohongshu' | 'generic'"""
    for platform, domains in _PLATFORM_RULES:
        if any(d in url for d in domains):
            return platform
    return "generic"


def _get_importer(platform: str):
    if platform == "wechat":
        return WechatImporter()
    if platform == "xiaohongshu":
        return XiaohongshuImporter()
    return None


async def _fetch_async(url: str) -> ImportResult:
    platform = detect_platform(url)
    importer = _get_importer(platform)
    if importer is None:
        raise ValueError(f"Platform '{platform}' not supported. Use generic capture.")
    return await importer.import_from_url(url)


def fetch_url(url: str) -> ImportResult:
    """同步入口，供 obsidian_writer.py 调用"""
    return asyncio.run(_fetch_async(url))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch content from supported platforms")
    parser.add_argument("--url", required=True)
    args = parser.parse_args()

    result = fetch_url(args.url)
    print(json.dumps({
        "title": result.title,
        "content": result.content,
        "summary": result.summary,
        "platform": result.platform,
        "source_url": result.source_url,
        "metadata": result.metadata or {},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

退出条件：
- `python skills/obsidian/importers/router.py --url "https://mp.weixin.qq.com/s/test"` 不抛 ImportError
- `detect_platform("https://mp.weixin.qq.com/s/xxx")` 返回 `"wechat"`
- `detect_platform("https://google.com")` 返回 `"generic"`

---

### Task 4 — 新建 `tests/test_importers.py`

**文件：** `tests/test_importers.py`（新建）

所有测试用 mock/fixture，不做真实网络请求。

```python
测试用例：
test_detect_platform_wechat          # mp.weixin.qq.com → "wechat"
test_detect_platform_xiaohongshu     # www.xiaohongshu.com → "xiaohongshu"
test_detect_platform_generic         # google.com → "generic"
test_wechat_parse_content            # mock HTML → ImportResult 字段正确
test_wechat_extract_title            # 多 selector 降级逻辑
test_xiaohongshu_parse_meta_fallback # SSR 失败时 og:meta 降级
test_import_result_fields            # ImportResult dataclass 默认值
```

`WechatImporter` 的 `parse_content` 测试：提供包含 `<h1 id="activity-name">标题</h1>` 和 `<div id="js_content"><p>正文</p></div>` 的 HTML，验证 `ImportResult.title == "标题"` 且 `"正文" in result.content`。

运行：`python -m pytest tests/test_importers.py -q`，全部通过。

---

## Phase B：LLM 关系提取（Tasks 5-8）

### Task 5 — 新建 `skills/obsidian/relation_extractor.py`

**文件：** `skills/obsidian/relation_extractor.py`（新建）

完整实现：

```python
"""
relation_extractor.py — 用 LLM 从笔记提取概念，匹配 vault 笔记，生成 wikilinks。

依赖：anthropic（pip install anthropic）
环境变量：
  ANTHROPIC_API_KEY   — 必须
  OBSIDIAN_RELATION_EXTRACT=1  — 启用开关（默认关）
"""

from __future__ import annotations

import json
import logging
import os
import re
import warnings
from pathlib import Path

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_CONTENT_TOKENS = 1500
_RELATED_SECTION = "相关概念"
_NOTE_TYPES_ENABLED = {"literature", "concept", "topic", "project"}


# ---------------------------------------------------------------------------
# Content truncation（移植自 SparkNoteAI knowledge_graph.py）
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    chinese = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    english = sum(1 for c in text if c.isascii() and c.isalpha())
    return int(chinese * 1.5 + english * 0.25)


def truncate_content_smart(content: str, max_tokens: int = _MAX_CONTENT_TOKENS) -> str:
    """保留首尾段落，中间按长度降序填充，来自 SparkNoteAI。"""
    if not content or _estimate_tokens(content) <= max_tokens:
        return content
    paragraphs = content.split("\n\n")
    if len(paragraphs) <= 2:
        # 段落太少，直接截断字符
        limit = max_tokens * 2  # 粗略字符数上限
        return content[:limit]
    first, last = paragraphs[0], paragraphs[-1]
    base_tokens = _estimate_tokens(first) + _estimate_tokens(last)
    budget = max_tokens - base_tokens
    middle = sorted(paragraphs[1:-1], key=lambda p: _estimate_tokens(p), reverse=True)
    selected = []
    for p in middle:
        cost = _estimate_tokens(p)
        if budget - cost >= 0:
            selected.append(p)
            budget -= cost
    result_parts = [first] + selected + [last]
    return "\n\n".join(result_parts)


# ---------------------------------------------------------------------------
# JSON 解析（移植自 SparkNoteAI knowledge_graph.py _extract_json_from_response）
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> str:
    """从 LLM 返回文本中提取 JSON，处理 markdown 代码块和前缀文字。"""
    # 方法 1：markdown 代码块
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if json_match:
        candidate = json_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass
    # 方法 2：找第一个 { 或 [
    for start_char in ("{", "["):
        start = text.find(start_char)
        if start == -1:
            continue
        candidate = text[start:]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            depth, in_string, escape_next = 0, False, False
            for i, ch in enumerate(candidate):
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\":
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch in ("{", "["):
                    depth += 1
                elif ch in ("}", "]"):
                    depth -= 1
                    if depth == 0:
                        try:
                            json.loads(candidate[: i + 1])
                            return candidate[: i + 1]
                        except json.JSONDecodeError:
                            break
    return text


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------

def _call_llm(system_prompt: str, user_prompt: str) -> str:
    import anthropic  # 延迟导入，不强依赖
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return msg.content[0].text


# ---------------------------------------------------------------------------
# 概念提取
# ---------------------------------------------------------------------------

def extract_concepts(title: str, content: str) -> list[dict]:
    """调用 LLM 提取概念，返回 [{"name": "...", "type": "...", "description": "..."}]"""
    system_prompt = (
        "你是一个专业的知识图谱构建助手。从笔记中提取 3-10 个核心概念。\n"
        "类型：concept（核心概念）/ topic（主题类别）/ entity（人物/组织/工具）。\n"
        "返回严格 JSON 格式，不要包含其他说明文字。"
    )
    user_prompt = (
        f"笔记标题：{title}\n"
        f"笔记内容：\n{truncate_content_smart(content)}\n\n"
        '返回格式：{"concepts": [{"name": "...", "type": "...", "description": "..."}]}'
    )
    try:
        raw = _call_llm(system_prompt, user_prompt)
        data = json.loads(_extract_json(raw))
        if isinstance(data, list):
            return data
        return data.get("concepts", []) if isinstance(data, dict) else []
    except Exception as e:
        logger.warning(f"extract_concepts failed: {e}")
        return []


# ---------------------------------------------------------------------------
# 概念 → vault 匹配
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    name = re.sub(r"[^\w\u4e00-\u9fff]", "", name)
    return name.lower().strip()


def match_to_vault(concepts: list[dict], vault: Path) -> list[str]:
    """
    将概念名与 vault 全量 note stems 做匹配，返回 [[stem]] 格式的 wikilinks。
    匹配策略：精确 > 归一化 > 包含（stem 长度 ≤ 20）。
    """
    all_notes = list(vault.rglob("*.md"))
    stems = {f.stem for f in all_notes}
    stems_norm = {_normalize(s): s for s in stems}

    links = []
    for concept in concepts:
        name = concept.get("name", "").strip()
        if not name:
            continue
        # 精确匹配
        if name in stems:
            links.append(f"[[{name}]]")
            continue
        # 归一化匹配
        name_norm = _normalize(name)
        if name_norm and name_norm in stems_norm:
            links.append(f"[[{stems_norm[name_norm]}]]")
            continue
        # 包含匹配（name ⊂ stem 或 stem ⊂ name，stem ≤ 20 字符）
        for stem in stems:
            if len(stem) > 20:
                continue
            if name_norm in _normalize(stem) or _normalize(stem) in name_norm:
                links.append(f"[[{stem}]]")
                break

    # 去重，保留顺序
    seen: set[str] = set()
    result = []
    for link in links:
        if link not in seen:
            seen.add(link)
            result.append(link)
    return result


# ---------------------------------------------------------------------------
# 写回笔记
# ---------------------------------------------------------------------------

def append_related_concepts(note_path: Path, wikilinks: list[str]) -> None:
    """在笔记末尾追加或更新 ## 相关概念 section，增量不覆盖。"""
    if not wikilinks:
        return
    text = note_path.read_text(encoding="utf-8", errors="replace")
    section_header = f"## {_RELATED_SECTION}"

    existing_links: set[str] = set()
    if section_header in text:
        # 提取已有 section 内容
        pat = re.compile(rf"(?ms)^## {re.escape(_RELATED_SECTION)}\n(.*?)(?=^## |\Z)")
        m = pat.search(text)
        if m:
            existing_links = set(re.findall(r"\[\[[^\]]+\]\]", m.group(1)))

    new_links = [lnk for lnk in wikilinks if lnk not in existing_links]
    if not new_links:
        return

    addition = "\n".join(new_links)
    if section_header in text:
        # 追加到已有 section 末尾
        text = re.sub(
            rf"(?ms)(^## {re.escape(_RELATED_SECTION)}\n)(.*?)(?=^## |\Z)",
            lambda m: m.group(1) + m.group(2).rstrip() + "\n" + addition + "\n",
            text,
            count=1,
        )
    else:
        # 新增 section
        if not text.endswith("\n"):
            text += "\n"
        text += f"\n{section_header}\n{addition}\n"

    note_path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def extract_and_link(vault: Path, note_path: Path) -> list[str]:
    """读取笔记 → 提取概念 → 匹配 vault → 写回 wikilinks。"""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY not set")

    text = note_path.read_text(encoding="utf-8", errors="replace")
    # 去掉 frontmatter
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:].lstrip()

    title = note_path.stem
    concepts = extract_concepts(title, text)
    if not concepts:
        return []

    links = match_to_vault(concepts, vault)
    # 排除笔记自身
    self_link = f"[[{note_path.stem}]]"
    links = [lnk for lnk in links if lnk != self_link]

    if links:
        append_related_concepts(note_path, links)
    return links
```

退出条件：
- `truncate_content_smart("x" * 5000)` 返回比输入短的字符串
- `match_to_vault([{"name": "RAG"}], vault)` 在 vault 存在 `Concept - RAG.md` 时返回 `["[[Concept - RAG]]"]`
- 环境变量未设置时 `extract_and_link` 抛 `EnvironmentError`

---

### Task 6 — `obsidian_writer.py`：集成 relation_extractor

**文件：** `skills/obsidian/obsidian_writer.py`

**6a — 顶部导入（与 profile_manager 相同模式）：**

```python
try:
    from .relation_extractor import extract_and_link as _extract_and_link
except ImportError:
    try:
        from relation_extractor import extract_and_link as _extract_and_link
    except ImportError:
        _extract_and_link = None
```

**6b — `write_note()` 函数末尾，紧接 memory_manager 更新之后：**

```python
# 关系提取：提取概念 wikilinks（需 ANTHROPIC_API_KEY + OBSIDIAN_RELATION_EXTRACT=1）
if (
    not is_draft
    and note_type in {"literature", "concept", "topic", "project"}
    and _extract_and_link is not None
    and os.environ.get("OBSIDIAN_RELATION_EXTRACT") == "1"
):
    try:
        links = _extract_and_link(vault, filepath)
        if links:
            # 结果仅供日志，不影响返回值
            pass
    except Exception as _rel_err:
        warnings.warn(f"Relation extraction failed (non-fatal): {_rel_err}", stacklevel=2)
```

退出条件：
- `OBSIDIAN_RELATION_EXTRACT` 未设置时，`write_note()` 行为与之前完全一致
- 设置后，写入成功的 literature 笔记末尾出现 `## 相关概念` section（需要有 vault）

---

### Task 7 — 新建 `tests/test_relation_extractor.py`

**文件：** `tests/test_relation_extractor.py`（新建）

所有 LLM 调用用 `unittest.mock.patch` mock，不做真实 API 请求。

```
测试用例：
test_truncate_content_short            # 短内容原样返回
test_truncate_content_long             # 长内容被截断
test_extract_json_markdown_block       # ```json ... ``` 解析正确
test_extract_json_with_prefix_text     # "好的，结果如下：{...}" 解析正确
test_extract_concepts_returns_list     # mock LLM 返回，验证解析
test_match_to_vault_exact              # 精确匹配
test_match_to_vault_normalized         # 归一化匹配（去标点）
test_match_to_vault_no_match           # 不存在的概念返回 []
test_append_new_section                # 不存在 section 时新增
test_append_existing_section_incremental  # 已有 section 时增量追加，不覆盖
test_append_dedup                      # 重复 wikilink 不重复写入
test_extract_and_link_no_api_key       # 无 ANTHROPIC_API_KEY 抛 EnvironmentError
test_extract_and_link_disabled         # OBSIDIAN_RELATION_EXTRACT 未设置时不调用 LLM
```

运行：`python -m pytest tests/test_relation_extractor.py -q`，全部通过。

---

### Task 8 — SKILL.md：更新 capture 命令说明

**文件：** `skills/obsidian/SKILL.md`

在 `capture` 模式说明中补充：

```markdown
### 平台识别

URL 自动路由到对应适配器：

| 域名 | 平台 | 适配器 |
|------|------|--------|
| mp.weixin.qq.com | 微信公众号 | WechatImporter |
| www.xiaohongshu.com / xhslink.com | 小红书 | XiaohongshuImporter |
| 其他 | 通用网页 | 现有逻辑 |

微信/小红书 URL 调用流程：
1. `python importers/router.py --url <url>` 获取 ImportResult JSON
2. 从 JSON 中提取 title / content / metadata
3. 按 literature 类型提取核心观点/方法要点
4. 调用 `obsidian_writer.py --type literature` 写入
```

退出条件：
- SKILL.md 包含平台识别说明和调用流程

---

### Task 9 — 全量测试 & 提交

```bash
python -m pytest tests/ -q
```

预期：原有 194+ 测试 + 新增 ~20 个测试全部通过。

提交信息：
```
feat: add multi-platform capture adapters and LLM relation extraction

- importers/: wechat and xiaohongshu importers ported from SparkNoteAI
- relation_extractor.py: extract concepts via Anthropic API, match to vault stems, append wikilinks
- obsidian_writer.py: integrate relation_extractor (opt-in via OBSIDIAN_RELATION_EXTRACT=1)
- SKILL.md: platform detection guide for capture command
```

---

## Execution Order

```
Task 1 → Task 2 → Task 3 → Task 4   (Phase A，顺序执行)
Task 5 → Task 6 → Task 7            (Phase B，顺序执行)
Task 8                               (可与 Phase B 并行)
Task 9                               (最后)
```

Phase A 和 Phase B 可以并行。

---

## Key Constraints

- **零强制新依赖**：`httpx`/`beautifulsoup4`/`anthropic` 均为可选；未安装时对应功能优雅降级（warn，不 raise）
- **不破坏现有测试**：194+ 个测试必须继续通过
- **relation_extractor 默认关闭**：需显式设置 `OBSIDIAN_RELATION_EXTRACT=1`
- **同步风格**：所有 Python 函数对外接口保持同步，async 只在 importer 内部
- **不改 CLI 接口**：现有 `--mode capture` 参数不变
