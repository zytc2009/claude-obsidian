"""
templates.py — Note rendering and per-type configuration.

Pure templating: takes ``(title, fields, is_draft)`` and returns the
markdown string. No IO, no side effects. ``obsidian_writer`` consumes
these to produce final note files.

The :data:`NOTE_CONFIG` table drives:
  - filename prefix (``Literature - Foo.md``)
  - target subdirectory (``03-Knowledge/Literature``)
  - required fields used for draft routing
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

NOTE_CONFIG: dict[str, dict] = {
    "literature": {
        "prefix": "Literature",
        "target": "03-Knowledge/Literature",
        "required": ["核心观点", "方法要点"],
    },
    "concept": {
        "prefix": "Concept",
        "target": "03-Knowledge/Concepts",
        "required": ["一句话定义", "核心机制"],
    },
    "topic": {
        "prefix": "Topic",
        "target": "03-Knowledge/Topics",
        "required": ["主题说明", "当前结论"],
    },
    "project": {
        "prefix": "Project",
        "target": "02-Projects",
        "required": ["项目描述", "排查过程", "解决方案"],
    },
    "moc": {
        "prefix": "MOC",
        "target": "03-Knowledge/MOCs",
        "required": [],
    },
    "article": {
        "prefix": "Article",
        "target": "06-Articles",
        "required": ["核心论点", "正文"],
    },
}


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------


def is_draft_by_content(note_type: str, fields: dict) -> bool:
    """Return True if more than half of required fields are empty."""

    required = NOTE_CONFIG.get(note_type, {}).get("required", [])
    if not required:
        return False
    empty_count = sum(1 for f in required if not fields.get(f, "").strip())
    return empty_count > len(required) / 2


def get_target_path(vault: Path, note_type: str, is_draft: bool) -> Path:
    """Return the directory path where the note should be written."""

    if is_draft:
        return vault / "00-Inbox"
    return vault / NOTE_CONFIG[note_type]["target"]


def make_filename(prefix: str, title: str, target_dir: Path) -> str:
    """Return a filename, appending today's date if a collision exists."""

    base = f"{prefix} - {title}.md"
    if not (target_dir / base).exists():
        return base
    today = date.today().strftime("%Y-%m-%d")
    return f"{prefix} - {title} {today}.md"


# ---------------------------------------------------------------------------
# Frontmatter renderer
# ---------------------------------------------------------------------------


def _f(fields: dict, key: str) -> str:
    """Return field value or empty string if missing."""

    return fields.get(key, "").strip()


def render_frontmatter(note_type: str, fields: dict, is_draft: bool = False) -> str:
    """Render the ``---``-delimited frontmatter block for a note.

    Behavior parity with ``obsidian_writer._frontmatter``.
    """

    today = date.today().strftime("%Y-%m-%d")
    source = fields.get("source", "").strip()
    author = fields.get("author", "").strip()
    platform = fields.get("platform", "").strip()
    source_url = fields.get("source_url", "").strip()
    status = "draft" if is_draft else ("review" if note_type == "article" else "active")
    extra = ""
    if platform:
        extra += f"platform: {platform}\n"
    if source_url:
        extra += f"source_url: {source_url}\n"
    if note_type == "article":
        source_notes = fields.get("source_notes", "").strip()
        target_audience = fields.get("target_audience", "").strip()
        target_value = target_audience if target_audience else '""'
        extra = extra + (
            f"source_notes: {source_notes or '[]'}\n"
            f"target_audience: {target_value}\n"
        )
    return (
        f"---\n"
        f"type: {note_type}\n"
        f"status: {status}\n"
        f"topic: []\n"
        f"tags: []\n"
        f"source: {source}\n"
        f"author: {author}\n"
        f"{extra}"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"reviewed: false\n"
        f"---"
    )


# ---------------------------------------------------------------------------
# Per-type body renderers
# ---------------------------------------------------------------------------


def render_literature(title: str, fields: dict, is_draft: bool = False) -> str:
    fm = render_frontmatter("literature", fields, is_draft)
    return f"""{fm}

# 资料信息
- 标题：{title}
- 作者：{_f(fields, "author")}
- 类型：{_f(fields, "类型")}
- 链接：{_f(fields, "source")}

# 这份资料试图解决什么问题
{_f(fields, "解决的问题")}

# 核心观点
{_f(fields, "核心观点")}

# 方法要点
{_f(fields, "方法要点")}

# 原文主要内容
{_f(fields, "原文主要内容")}

# 值得记住的细节
{_f(fields, "细节")}

# 我的疑问
{_f(fields, "我的疑问")}

# 可转化为哪些概念卡
{_f(fields, "可转化概念")}

# 与已有知识的连接
{_f(fields, "知识连接")}
"""


def render_concept(title: str, fields: dict, is_draft: bool = False) -> str:
    fm = render_frontmatter("concept", fields, is_draft)
    return f"""{fm}

# {title}

# 一句话定义
{_f(fields, "一句话定义")}

# 解决什么问题
{_f(fields, "解决什么问题")}

# 核心机制
{_f(fields, "核心机制")}

# 关键公式 / 关键流程
{_f(fields, "关键公式或流程")}

# 优点
{_f(fields, "优点")}

# 局限
{_f(fields, "局限")}

# 适用场景
{_f(fields, "适用场景")}

# 常见误区
{_f(fields, "常见误区")}

# 我的理解
{_f(fields, "我的理解")}

# 相关链接
{_f(fields, "相关链接")}
"""


def render_topic(title: str, fields: dict, is_draft: bool = False) -> str:
    fm = render_frontmatter("topic", fields, is_draft)
    return f"""{fm}

# {title}

# 主题说明
{_f(fields, "主题说明")}

# 核心问题
{_f(fields, "核心问题")}

# 重要资料
{_f(fields, "重要资料")}

# 相关项目
{_f(fields, "相关项目")}

# 当前结论
{_f(fields, "当前结论")}

# 未解决问题
{_f(fields, "未解决问题")}
"""


def render_project(title: str, fields: dict, is_draft: bool = False) -> str:
    fm = render_frontmatter("project", fields, is_draft)
    return f"""{fm}

# {title}

# 项目描述
{_f(fields, "项目描述")}

# 原因分析
{_f(fields, "原因分析")}

# 排查过程
{_f(fields, "排查过程")}

# 解决方案
{_f(fields, "解决方案")}

# 结果验证
{_f(fields, "结果验证")}

# 风险与遗留问题
{_f(fields, "风险与遗留问题")}
"""


def render_moc(title: str, fields: dict, is_draft: bool = False) -> str:
    fm = render_frontmatter("moc", fields, is_draft)
    links = fields.get("links", "").strip()
    return f"""{fm}

# {title}

# 主题地图

# 概念
{links if links else ""}

# 资料

# 项目

# 常见问题

# 输出内容

"""


def render_article(title: str, fields: dict, is_draft: bool = False) -> str:
    fm = render_frontmatter("article", fields, is_draft)
    source_notes = fields.get("source_notes", "").strip()
    target_audience = fields.get("target_audience", "").strip()
    return f"""{fm}

# {title}

## 核心论点
{_f(fields, "核心论点")}

## 正文
{_f(fields, "正文")}

## 结语
{_f(fields, "结语")}

## 来源
{source_notes or "_待补充_"}

## 目标读者
{target_audience or "_待补充_"}
"""


# ---------------------------------------------------------------------------
# Daily note scaffold
# ---------------------------------------------------------------------------


DAILY_FRONTMATTER = """\
---
type: daily
status: active
topic: []
tags: []
created: {today}
updated: {today}
reviewed: false
---

# 今日目标

# 今日输入
- 课程：
- 论文：
- 博客：
- 代码仓库：

# 关键收获
-

# 遇到的问题
-

# 待验证假设
-

# 明日动作
-

# Fleeting
"""


RENDERERS: dict[str, callable] = {
    "literature": render_literature,
    "concept": render_concept,
    "topic": render_topic,
    "project": render_project,
    "moc": render_moc,
    "article": render_article,
}
