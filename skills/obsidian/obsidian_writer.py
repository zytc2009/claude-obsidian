"""
obsidian_writer.py — Write structured notes to an Obsidian vault.

Usage:
  python obsidian_writer.py --type literature --title "Title" \\
    --fields '{"核心观点": "..."}' --draft false

  python obsidian_writer.py --type fleeting \\
    --fields '{"content": "想到一个点...", "tags": "#ai"}'

  python obsidian_writer.py --type moc --title "AI Learning" \\
    --fields '{"links": "[[Concept - Transformer]]\\n[[Literature - Attention]]"}'

  python obsidian_writer.py --type literature --title "Title" \\
    --fields '{}' --draft true --dry-run
"""

import argparse
import json
import os
import re
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from .session_memory import SessionMemory
except ImportError:
    try:
        from session_memory import SessionMemory
    except ImportError:  # pragma: no cover - optional integration fallback
        SessionMemory = None  # type: ignore[assignment]

try:
    from .profile_manager import read_profile
except ImportError:
    try:
        from profile_manager import read_profile
    except ImportError:  # pragma: no cover - optional integration fallback
        read_profile = None  # type: ignore[assignment]

try:
    from .importers.router import fetch_url as capture_fetch_url
except ImportError:
    try:
        from importers.router import fetch_url as capture_fetch_url
    except ImportError:  # pragma: no cover - optional integration fallback
        capture_fetch_url = None  # type: ignore[assignment]

try:
    from .relation_extractor import extract_and_link as relation_extract_and_link
except ImportError:
    try:
        from relation_extractor import extract_and_link as relation_extract_and_link
    except ImportError:  # pragma: no cover - optional integration fallback
        relation_extract_and_link = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VAULT_PATH = Path(os.environ.get("OBSIDIAN_VAULT_PATH", "~/obsidian")).expanduser()

NOTE_CONFIG = {
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


def _safe_session_memory(vault: Path):
    """Return a session-memory instance when available, otherwise None."""
    if SessionMemory is None:
        return None
    try:
        return SessionMemory(vault, persist=True)
    except Exception:
        return None


def _session_rejected_targets(vault: Path, source_note: str) -> set[str]:
    """Return targets rejected in the current session for a given source note."""
    session = _safe_session_memory(vault)
    if session is None:
        return set()
    try:
        rejected = session.to_dict().get("rejected_targets", {}).get(source_note, [])
    except Exception:
        return set()
    return {str(item).strip() for item in rejected if str(item).strip()}


def _record_session_note(vault: Path, note_type: str, filepath: Path) -> None:
    """Update session memory for an explicit note write or update."""
    session = _safe_session_memory(vault)
    if session is None:
        return
    try:
        session.add_note(filepath.name)
        if note_type == "topic" or "Topics" in filepath.parts:
            session.add_topic(filepath.stem)
    except Exception:
        return


def record_session_query(vault: Path, query_text: str) -> None:
    """Persist a user query into session memory."""
    session = _safe_session_memory(vault)
    if session is None:
        return
    try:
        session.add_query(query_text)
    except Exception:
        return


def _resolve_session_note_refs(vault: Path, names: list[str]) -> list[Path]:
    """Resolve session note/topic names to concrete vault paths when they exist."""
    resolved: list[Path] = []
    seen: set[Path] = set()
    for name in names:
        label = str(name).strip()
        if not label:
            continue
        path = vault / label if label.endswith(".md") else None
        if path is not None and path.exists():
            if path not in seen:
                resolved.append(path)
                seen.add(path)
            continue
        pattern = label if label.endswith(".md") else f"{label}.md"
        matches = list(vault.rglob(pattern))
        for match in matches:
            if match not in seen:
                resolved.append(match)
                seen.add(match)
    return resolved


def find_session_relevant_notes(vault: Path, query_text: str = "", limit: int = 5) -> list[Path]:
    """Return current-session notes/topics ranked ahead of wider vault fallback.

    Ranking signals:
    - active topics before active notes
    - lexical overlap with the current query
    - recency within the session lists
    """
    session = _safe_session_memory(vault)
    if session is None:
        return []

    try:
        state = session.to_dict()
    except Exception:
        return []

    active_topics = list(state.get("active_topics", []))
    active_notes = list(state.get("active_notes", []))
    query_words = {word.lower() for word in _suggestion_keywords_from_stem(query_text)}

    candidates: list[tuple[int, int, Path]] = []
    seen: set[Path] = set()

    for idx, path in enumerate(_resolve_session_note_refs(vault, active_topics)):
        if path in seen:
            continue
        score = 100 - idx
        stem_words = {word.lower() for word in _suggestion_keywords_from_stem(path.stem)}
        overlap = len(query_words & stem_words)
        score += overlap * 50
        if query_words and overlap == 0:
            score -= 60
        candidates.append((score, idx, path))
        seen.add(path)

    for idx, path in enumerate(_resolve_session_note_refs(vault, active_notes)):
        if path in seen:
            continue
        score = 50 - idx
        stem_words = {word.lower() for word in _suggestion_keywords_from_stem(path.stem)}
        overlap = len(query_words & stem_words)
        score += overlap * 50
        if query_words and overlap == 0:
            score -= 30
        candidates.append((score, idx, path))
        seen.add(path)

    candidates.sort(key=lambda item: (-item[0], item[1], str(item[2])))
    return [path for _, _, path in candidates[:limit]]

# ---------------------------------------------------------------------------
# Routing utilities
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
# Template renderers
# ---------------------------------------------------------------------------

def _f(fields: dict, key: str) -> str:
    """Return field value or empty string if missing."""
    return fields.get(key, "").strip()


def _frontmatter(note_type: str, fields: dict, is_draft: bool = False) -> str:
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


def render_literature(title: str, fields: dict, is_draft: bool = False) -> str:
    fm = _frontmatter("literature", fields, is_draft)
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

# 我不认同或存疑的地方
{_f(fields, "存疑之处")}

# 可转化为哪些概念卡
{_f(fields, "可转化概念")}

# 可做哪些验证实验
{_f(fields, "验证实验")}

# 与已有知识的连接
{_f(fields, "知识连接")}
"""


def render_concept(title: str, fields: dict, is_draft: bool = False) -> str:
    fm = _frontmatter("concept", fields, is_draft)
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
    fm = _frontmatter("topic", fields, is_draft)
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
    fm = _frontmatter("project", fields, is_draft)
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
    fm = _frontmatter("moc", fields, is_draft)
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
    fm = _frontmatter("article", fields, is_draft)
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
# Fleeting note (append to DailyNote)
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


def append_fleeting(vault: Path, content: str, tags: str = "") -> Path:
    """Append a fleeting note item to today's daily note."""
    today = date.today().strftime("%Y-%m-%d")
    daily_dir = vault / "01-DailyNotes"
    daily_dir.mkdir(parents=True, exist_ok=True)
    filepath = daily_dir / f"{today}.md"

    now = datetime.now().strftime("%H:%M")
    tag_part = f" {tags}" if tags.strip() else ""
    item = f"- {now} {content}{tag_part}\n"

    if not filepath.exists():
        # Create new daily note with Fleeting section
        note_content = DAILY_FRONTMATTER.format(today=today) + item
        filepath.write_text(note_content, encoding="utf-8")
        return filepath

    text = filepath.read_text(encoding="utf-8")

    if "# Fleeting" in text:
        # Append after the last line of the Fleeting section
        # Find the section and append at its end
        lines = text.splitlines(keepends=True)
        insert_at = len(lines)
        in_fleeting = False
        for i, line in enumerate(lines):
            if line.strip() == "# Fleeting":
                in_fleeting = True
                continue
            if in_fleeting and line.startswith("# "):
                insert_at = i
                break
        lines.insert(insert_at, item)
        filepath.write_text("".join(lines), encoding="utf-8")
    else:
        # Append Fleeting section at end
        text = text.rstrip("\n") + "\n\n# Fleeting\n" + item
        filepath.write_text(text, encoding="utf-8")

    return filepath


# ---------------------------------------------------------------------------
# Renderer dispatch
# ---------------------------------------------------------------------------

RENDERERS = {
    "literature": render_literature,
    "concept": render_concept,
    "topic": render_topic,
    "project": render_project,
    "moc": render_moc,
    "article": render_article,
}

# ---------------------------------------------------------------------------
# Write note
# ---------------------------------------------------------------------------

def write_note(
    vault: Path,
    note_type: str,
    title: str,
    fields: dict,
    is_draft: bool,
    log_operation: bool = True,
) -> Path:
    """Render and write a note. Creates target directory if missing."""
    duplicate_path = _check_duplicate(vault, note_type, title)
    if duplicate_path is not None:
        return duplicate_path

    target_dir = get_target_path(vault, note_type, is_draft)
    target_dir.mkdir(parents=True, exist_ok=True)

    prefix = NOTE_CONFIG[note_type]["prefix"]
    filename = make_filename(prefix, title, target_dir)
    filepath = target_dir / filename

    content = RENDERERS[note_type](title, fields, is_draft)
    filepath.write_text(content, encoding="utf-8")
    _record_session_note(vault, note_type, filepath)

    # Incrementally update _index.md (skip drafts — they live in Inbox)
    if not is_draft:
        section_map = {
            "literature": "Literature",
            "concept": "Concepts",
            "topic": "Topics",
            "project": "Projects",
            "moc": "MOCs",
            "article": "Articles",
        }
        section = section_map.get(note_type)
        if section:
            _append_to_index(vault, filepath, section)
        if log_operation:
            append_operation_log(
                vault,
                "write",
                filepath.stem,
                [f"Action: created", f"Path: {filepath.relative_to(vault)}"],
            )

    # 记忆更新：提取关键词写入活性词库（跳过草稿和 fleeting/moc）
    if not is_draft and note_type not in ("moc", "fleeting"):
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent))
            from memory_manager import MemoryManager
            mm = MemoryManager(vault)
            mm.extract_and_upsert(note_type, title, fields, filepath.name)
            mm._save()
        except Exception as _mem_err:
            warnings.warn(f"Memory update failed (non-fatal): {_mem_err}", stacklevel=2)

    if (
        not is_draft
        and note_type in _NOTE_TYPES_REQUIRING_RELATION_EXTRACT
        and relation_extract_and_link is not None
        and os.environ.get("OBSIDIAN_RELATION_EXTRACT") == "1"
    ):
        try:
            links = relation_extract_and_link(vault, filepath)
            if links:
                warnings.warn(
                    f"Relation extraction added {len(links)} link(s) to {filepath.name}",
                    stacklevel=2,
                )
        except Exception as _rel_err:
            warnings.warn(f"Relation extraction failed (non-fatal): {_rel_err}", stacklevel=2)

    return filepath


def _capture_fields_from_import_result(import_result, user_fields: dict) -> tuple[str, dict]:
    """Build literature note fields from a platform import result."""
    fields = dict(user_fields)
    title = str(import_result.title or "").strip()
    platform = str(getattr(import_result, "platform", "") or "").strip()
    source_url = str(getattr(import_result, "source_url", "") or "").strip()
    summary = str(getattr(import_result, "summary", "") or "").strip()
    content = str(getattr(import_result, "content", "") or "").strip()
    metadata = getattr(import_result, "metadata", {}) or {}

    fields.setdefault("source", source_url)
    fields.setdefault("platform", platform)
    fields.setdefault("source_url", source_url)
    if summary and not fields.get("核心观点", "").strip():
        fields["核心观点"] = summary
    if content and not fields.get("原文主要内容", "").strip():
        fields["原文主要内容"] = content
    if isinstance(metadata, dict):
        author = str(metadata.get("author", "") or "").strip()
        if author and not fields.get("author", "").strip():
            fields["author"] = author
    return title, fields


# ---------------------------------------------------------------------------
# Vault init
# ---------------------------------------------------------------------------

VAULT_DIRS = [
    ("00-Inbox", None),
    ("01-DailyNotes", None),
    ("02-Projects", None),
    ("03-Knowledge", ["Concepts", "Literature", "MOCs", "Topics"]),
    ("04-Archive", None),
    ("05-Profile", None),
    ("06-Articles", None),
]


def init_vault(vault: Path) -> None:
    """Create all skill-managed directories and print the resulting tree."""
    created = []
    for top, subs in VAULT_DIRS:
        top_dir = vault / top
        if subs:
            for sub in subs:
                d = top_dir / sub
                if not d.exists():
                    d.mkdir(parents=True, exist_ok=True)
                    created.append(str(d.relative_to(vault)))
        else:
            if not top_dir.exists():
                top_dir.mkdir(parents=True, exist_ok=True)
                created.append(top)

    log_path = vault / _LOG_FILE
    if not log_path.exists():
        log_path.write_text("# Vault Operation Log\n", encoding="utf-8")
        created.append(_LOG_FILE)

    if created:
        print(f"[OK] Created {len(created)} director{'y' if len(created) == 1 else 'ies'}:")
        for d in created:
            print(f"  + {d}/")
    else:
        print("[OK] All directories already exist.")

    print()
    print(str(vault) + "/")
    for i, (top, subs) in enumerate(VAULT_DIRS):
        is_last_top = i == len(VAULT_DIRS) - 1
        top_pfx = "└── " if is_last_top else "├── "
        cont_pfx = "    " if is_last_top else "│   "
        top_dir = vault / top
        print(f"{top_pfx}{top}/")
        if subs:
            for j, sub in enumerate(subs):
                is_last_sub = j == len(subs) - 1
                sub_pfx = cont_pfx + ("└── " if is_last_sub else "├── ")
                file_pfx = cont_pfx + ("    " if is_last_sub else "│   ")
                print(f"{sub_pfx}{sub}/")
                files = sorted((top_dir / sub).glob("*.md")) if (top_dir / sub).exists() else []
                for k, f in enumerate(files):
                    leaf = "└── " if k == len(files) - 1 else "├── "
                    print(f"{file_pfx}{leaf}{f.name}")
        else:
            files = sorted(top_dir.glob("*.md")) if top_dir.exists() else []
            for k, f in enumerate(files):
                leaf = "└── " if k == len(files) - 1 else "├── "
                print(f"{cont_pfx}{leaf}{f.name}")


# ---------------------------------------------------------------------------
# Link suggestion
# ---------------------------------------------------------------------------

def _suggestion_keywords_from_stem(stem: str) -> list:
    """Extract meaningful keywords from a note stem for link suggestion."""
    normalized_stem = re.sub(r"\s\d{4}-\d{2}-\d{2}$", "", stem)
    stop_words = {
        "with", "from", "that", "this", "into", "over", "under",
        "about", "have", "been", "were", "will", "does", "their",
    }
    type_prefixes = ("Literature", "Concept", "Topic", "Project", "MOC")

    keywords = []
    for word in re.split(r"[\s\-_]+", normalized_stem):
        if not word:
            continue
        if word.startswith(type_prefixes):
            continue
        if re.fullmatch(r"\d{4}(?:\d{2}){0,2}", word):
            continue
        if len(word) >= 4 or (len(word) == 3 and word.isupper()):
            if word.lower() not in stop_words:
                keywords.append(word)
    return keywords


def _load_feedback_adjustments(
    vault: Path, suggestion_type: str, source_note: str
) -> dict[str, dict[str, int]]:
    """Return per-target feedback counts for a given source note and suggestion type."""
    events_path = vault / _EVENTS_FILE
    if not events_path.exists():
        return {}

    adjustments: dict[str, dict[str, int]] = {}
    try:
        with events_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event_type") != "suggestion_feedback":
                    continue
                if event.get("suggestion_type") != suggestion_type:
                    continue
                if event.get("source_note") != source_note:
                    continue
                action = event.get("action")
                if action not in {"reject", "modify-accept"}:
                    continue
                for target in event.get("target_notes", []):
                    target_name = _normalize_feedback_target(target)
                    if not target_name:
                        continue
                    target_adjustments = adjustments.setdefault(
                        target_name, {"reject": 0, "modify-accept": 0}
                    )
                    target_adjustments[action] += 1
    except OSError:
        return {}
    return adjustments


def _normalize_feedback_target(target: str) -> str:
    """Normalize feedback targets to note stems so hints and scoring share one key."""
    target_name = str(target).strip()
    if not target_name:
        return ""
    target_path = Path(target_name)
    return target_path.stem.strip() or target_name


def suggest_links(vault: Path, new_note_path: Path) -> list:
    """Return MOC/Topic files that likely should link to the new note.

    Heuristic: search MOCs and Topics for any word from the new note's stem
    that is ≥ 4 characters, to avoid spurious matches on short tokens.
    Returns a list of (relative_path, section_hint) tuples.
    """
    stem = new_note_path.stem  # e.g. "Literature - Attention Is All You Need"
    # Extract meaningful words (≥4 chars, not common stop words)
    words = _suggestion_keywords_from_stem(stem)
    if not words:
        return []

    feedback_adjustments = _load_feedback_adjustments(vault, "link", stem)
    session_rejections = _session_rejected_targets(vault, stem)
    candidates = []
    search_plan = [
        ("03-Knowledge/Topics", 2, "# 相关项目" if new_note_path.stem.startswith("Project - ") else "# 重要资料"),
        ("03-Knowledge/MOCs", 1, "# 资料"),
    ]
    max_suggestions = 3

    for search_dir, base_score, section in search_plan:
        target_dir = vault / search_dir
        if not target_dir.exists():
            continue
        for md_file in target_dir.glob("*.md"):
            if md_file == new_note_path:
                continue
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if new_note_path.stem in text:
                continue

            title_text = md_file.stem.lower()
            body_text = text.lower()
            title_words = [w for w in words if w.lower() in title_text]
            body_words = [w for w in words if w.lower() in body_text]
            title_matches = len(title_words)
            body_matches = len(body_words)
            raw_score = base_score + title_matches * 2 + body_matches
            penalty_meta = feedback_adjustments.get(md_file.stem, {})
            penalty = penalty_meta.get("reject", 0) * 3 + penalty_meta.get("modify-accept", 0)
            if md_file.stem in session_rejections:
                penalty += 4
            score = raw_score - penalty
            if score <= base_score:
                continue
            strength = "high" if base_score == 2 else "medium"
            reason_parts = [f"strength={strength}"]
            if title_words:
                reason_parts.append(f"title={', '.join(title_words[:3])}")
            if body_words:
                reason_parts.append(f"body={', '.join(body_words[:3])}")
            if penalty_meta.get("reject", 0):
                reason_parts.append(f"feedback=rejectx{penalty_meta['reject']}")
            if penalty_meta.get("modify-accept", 0):
                reason_parts.append(
                    f"feedback=modify-acceptx{penalty_meta['modify-accept']}"
                )
            if md_file.stem in session_rejections:
                reason_parts.append("session=reject")
            reason = "; ".join(reason_parts)
            candidates.append((score, md_file.relative_to(vault), f"{section}; {reason}"))

    candidates.sort(key=lambda item: (-item[0], str(item[1])))
    return [(rel, section) for _, rel, section in candidates[:max_suggestions]]


def suggest_new_topic(new_note_path: Path, suggestions: list) -> str:
    """Suggest a new topic name when no existing topic is a strong fit."""
    if "Topics" in new_note_path.parts or new_note_path.stem.startswith("Topic - "):
        return ""

    has_topic_match = any("Topics" in Path(rel).parts for rel, _ in suggestions)
    if has_topic_match:
        return ""

    phrase = _topic_candidate_from_stem(new_note_path.stem)
    if not phrase:
        return ""

    return f"Consider creating: Topic - {phrase}"


def _topic_candidate_from_stem(stem: str) -> str:
    """Extract a reasonable topic candidate from a note stem."""
    prefix_stop = {"literature", "concept", "topic", "project", "moc"}
    suffix_stop = {
        "survey", "surveys", "notes", "note", "draft", "article", "paper",
        "blog", "overview", "guide", "tutorial", "summary",
    }
    words = [w for w in re.split(r"[\s\-_]+", stem) if w]
    while words and words[0].lower() in prefix_stop:
        words.pop(0)
    while words and words[-1].lower() in suffix_stop:
        words.pop()

    filtered = [w for w in words if len(w) >= 3]
    if not filtered:
        return ""
    return " ".join(filtered[:4])


# ---------------------------------------------------------------------------
# Topic scout
# ---------------------------------------------------------------------------

_SCOUT_STOP_WORDS = {
    # English
    "the", "and", "for", "with", "from", "that", "this", "into", "over",
    "under", "about", "have", "been", "were", "will", "does", "their",
    "using", "based", "more", "less", "also", "when", "where", "what",
    "how", "why", "can", "its", "are", "not", "but", "has", "had",
    # Type prefixes (not useful for clustering)
    "literature", "concept", "topic", "project", "moc",
    # Generic note words
    "notes", "note", "draft", "article", "paper", "blog", "survey",
    "overview", "guide", "tutorial", "summary",
}

_SCOUT_SCAN_DIRS = {"00-Inbox", "03-Knowledge"}
_SCOUT_SKIP_SUBDIRS = {"Topics"}   # topics are the target, not candidates
_SCOUT_MIN_CLUSTER = 2
_SCOUT_SIMILARITY_THRESHOLD = 0.10   # lowered from 0.15 for better CJK/mixed recall
_SCOUT_TOP_WORDS = 4   # words in suggested topic name

# Chinese section header patterns that are note-template boilerplate
_SCOUT_BOILERPLATE = {
    "资料信息", "与已有知识的连接", "原文主要内容", "核心观点", "方法要点",
    "存疑之处", "可转化概念", "验证实验", "知识连接", "细节",
    "一句话定义", "解决什么问题", "核心机制", "关键公式或流程", "优点",
    "局限", "适用场景", "常见误区", "我的理解", "相关链接",
    "主题说明", "核心问题", "重要资料", "相关项目", "当前结论", "未解决问题",
    "项目描述", "原因分析", "排查过程", "解决方案", "结果验证", "风险与遗留问题",
}


def _split_mixed_tokens(text: str) -> list[str]:
    """Split text on whitespace/punctuation and also at CJK↔ASCII boundaries."""
    # First split on common separators
    parts = re.split(r"[\s\-_：:与、，。！？（）()【】\[\]《》<>「」\|/\\]+", text)
    result = []
    for part in parts:
        if not part:
            continue
        # Further split at CJK↔ASCII transition boundaries
        sub = re.sub(r"([A-Za-z0-9])(?=[\u4e00-\u9fff])", r"\1 ", part)
        sub = re.sub(r"([\u4e00-\u9fff])(?=[A-Za-z0-9])", r"\1 ", sub)
        result.extend(sub.split())
    return result


def _normalize_token(t: str) -> str | None:
    """Normalize a raw token; return None if it should be discarded."""
    t = t.lower().strip()
    if len(t) < 3:
        return None
    if t in _SCOUT_STOP_WORDS or t in _SCOUT_BOILERPLATE:
        return None
    if re.fullmatch(r"[\d\-:]+", t):
        return None
    return t


def _scout_keywords(stem: str, fm: dict, body: str) -> dict[str, int]:
    """Return a weighted keyword counter for clustering.

    Stem/tag keywords get weight 3 (high signal); body keywords get weight 1.
    Returns a dict[keyword → weight] used for weighted Jaccard similarity.
    """
    counter: dict[str, int] = {}

    def add(tokens: list[str], weight: int) -> None:
        for t in tokens:
            t = _normalize_token(t)
            if t:
                counter[t] = max(counter.get(t, 0), weight)

    # Stem — highest weight
    add(_split_mixed_tokens(stem), weight=3)

    # Frontmatter tags — high weight
    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    for tag in tags:
        add(_split_mixed_tokens(str(tag)), weight=3)

    # Body — strip heading lines and placeholders first
    clean_body = re.sub(r"^#+\s.*$", "", body, flags=re.MULTILINE)
    clean_body = clean_body.replace("_待补充_", "")
    add(_split_mixed_tokens(clean_body[:500]), weight=1)

    return counter


def _jaccard(a: dict[str, int], b: dict[str, int]) -> float:
    """Weighted Jaccard similarity between two keyword counters.

    Uses min(w_a, w_b) / max(w_a, w_b) summed over the union of keys.
    """
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    numerator = sum(min(a.get(k, 0), b.get(k, 0)) for k in keys)
    denominator = sum(max(a.get(k, 0), b.get(k, 0)) for k in keys)
    return numerator / denominator if denominator else 0.0


_SCOUT_STEM_THRESHOLD = 0.25   # stricter threshold for stem-only path

def _stem_jaccard(a: dict[str, int], b: dict[str, int], min_weight: int = 3) -> float:
    """Jaccard similarity using only high-weight (stem/tag) keywords."""
    a_high = {k for k, v in a.items() if v >= min_weight}
    b_high = {k for k, v in b.items() if v >= min_weight}
    if not a_high or not b_high:
        return 0.0
    return len(a_high & b_high) / len(a_high | b_high)


def _cluster_notes(
    notes: list[tuple[Path, dict[str, int]]],
    threshold: float = _SCOUT_SIMILARITY_THRESHOLD,
) -> list[list[tuple[Path, dict[str, int]]]]:
    """Greedy single-linkage clustering by Jaccard keyword overlap."""
    clusters: list[list[tuple[Path, dict[str, int]]]] = []
    assigned: set[int] = set()

    for i, (path_i, kw_i) in enumerate(notes):
        if i in assigned:
            continue
        cluster = [(path_i, kw_i)]
        assigned.add(i)
        # Expand: any unassigned note with similarity > threshold to any cluster member
        changed = True
        while changed:
            changed = False
            for j, (path_j, kw_j) in enumerate(notes):
                if j in assigned:
                    continue
                if any(
                    _jaccard(kw_j, kw_m) >= threshold
                    or _stem_jaccard(kw_j, kw_m) >= _SCOUT_STEM_THRESHOLD
                    for _, kw_m in cluster
                ):
                    cluster.append((path_j, kw_j))
                    assigned.add(j)
                    changed = True
        clusters.append(cluster)

    return clusters


def _suggest_cluster_name(cluster: list[tuple[Path, dict[str, int]]]) -> str:
    """Pick a topic name from keywords shared across the most notes in the cluster.

    Prefers stem-weight keywords (weight >= 3) appearing in ≥2 notes.
    Falls back to any shared keyword if no high-weight ones qualify.
    """
    # Count in how many notes each keyword appears, weighted by max weight
    note_count: dict[str, int] = {}
    max_weight: dict[str, int] = {}
    for _, counter in cluster:
        for kw, w in counter.items():
            note_count[kw] = note_count.get(kw, 0) + 1
            max_weight[kw] = max(max_weight.get(kw, 0), w)

    # Strong candidates: appear in ≥2 notes AND are stem-level keywords (weight ≥ 3)
    strong = {w for w, c in note_count.items() if c >= 2 and max_weight[w] >= 3}
    if not strong:
        # Fallback: any keyword in ≥2 notes
        strong = {w for w, c in note_count.items() if c >= 2}
    if not strong:
        strong = set(max_weight)

    ranked = sorted(strong, key=lambda w: (-note_count[w], -max_weight[w]))
    # Prefer pure-ASCII tokens for readability; fall back to mixed if needed
    ascii_only = [w for w in ranked if re.fullmatch(r"[a-z0-9]+", w)]
    top = (ascii_only or ranked)[:_SCOUT_TOP_WORDS]
    return " ".join(w.capitalize() for w in top) if top else "Unknown"


def scout_topics(
    vault: Path,
    min_cluster_size: int = _SCOUT_MIN_CLUSTER,
    threshold: float = _SCOUT_SIMILARITY_THRESHOLD,
) -> None:
    """Find orphan notes and cluster them into proposed topic groups."""
    # Step 1: find stems already linked from any topic
    topic_dir = vault / "03-Knowledge" / "Topics"
    parented: set[str] = set()
    if topic_dir.exists():
        for topic_file in topic_dir.glob("*.md"):
            text = topic_file.read_text(encoding="utf-8", errors="replace")
            for link in _extract_wikilinks(text):
                parented.add(link)

    # Step 2: collect candidate notes (not in Topics, not already parented)
    candidates: list[tuple[Path, dict[str, int]]] = []
    for scan_dir_name in _SCOUT_SCAN_DIRS:
        scan_dir = vault / scan_dir_name
        if not scan_dir.exists():
            continue
        for note_file in scan_dir.rglob("*.md"):
            # Skip if inside a Topics subdir
            rel_parts = note_file.relative_to(vault).parts
            if any(p in _SCOUT_SKIP_SUBDIRS for p in rel_parts):
                continue
            if note_file.stem in parented:
                continue
            try:
                text = note_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = _parse_frontmatter(text)
            # Strip frontmatter from body
            body = re.sub(r"^---.*?---\s*", "", text, count=1, flags=re.DOTALL)
            keywords = _scout_keywords(note_file.stem, fm, body)
            candidates.append((note_file, keywords))

    if not candidates:
        print("✓ No orphan notes found — all notes have a topic parent.")
        return

    # Step 3: cluster
    all_clusters = _cluster_notes(candidates, threshold=threshold)
    clusters = [c for c in all_clusters if len(c) >= min_cluster_size]
    singletons = [c[0] for c in all_clusters if len(c) < min_cluster_size]

    print(f"[Topic Scout] Scanned {len(candidates)} orphan note(s)\n")

    if clusters:
        print(f"Found {len(clusters)} cluster(s) — consider creating a topic for each:\n")
        for idx, cluster in enumerate(clusters, 1):
            name = _suggest_cluster_name(cluster)
            print(f"Cluster {idx} ({len(cluster)} notes) → suggested: Topic - {name}")
            for note_path, _ in cluster:
                rel = note_path.relative_to(vault)
                print(f"  [[{note_path.stem}]]  ({rel})")
            print()

    if singletons:
        print(f"Singletons ({len(singletons)} note(s) with no close match):")
        for note_path, _ in singletons:
            rel = note_path.relative_to(vault)
            print(f"  [[{note_path.stem}]]  ({rel})")
        print()

    if not clusters and not singletons:
        print("✓ No orphan notes found.")


# ---------------------------------------------------------------------------
# Ingest preview helpers
# ---------------------------------------------------------------------------

def _classify_ingest_action(
    vault: Path, note_type: str, title: str, is_draft: bool
) -> tuple[str, "Path | None", Path]:
    """Return (action, existing_path_or_None, planned_write_path).

    action values:
      'create'            — no collision, net-new note
      'create (dated copy)' — base filename exists; existing note is unchanged,
                              a new dated copy will be written instead
    """
    target_dir = get_target_path(vault, note_type, is_draft)
    prefix = NOTE_CONFIG[note_type]["prefix"]
    base_path = target_dir / f"{prefix} - {title}.md"

    if not base_path.exists():
        return "create", None, base_path

    today = date.today().strftime("%Y-%m-%d")
    dated_path = target_dir / f"{prefix} - {title} {today}.md"
    return "create (dated copy)", base_path, dated_path


def _section_diff_summary(existing_path: Path, new_content: str) -> str:
    """One-line summary of which H1 sections differ between existing and new note."""
    existing_text = existing_path.read_text(encoding="utf-8", errors="replace")

    def _h1_sections(text: str) -> dict[str, str]:
        secs: dict[str, str] = {}
        cur: str | None = None
        buf: list[str] = []
        for line in text.splitlines():
            if line.startswith("# "):
                if cur is not None:
                    secs[cur] = " ".join(buf)
                cur = line[2:].strip()
                buf = []
            elif cur is not None and line.strip():
                buf.append(line.strip())
        if cur is not None:
            secs[cur] = " ".join(buf)
        return secs

    old = _h1_sections(existing_text)
    new = _h1_sections(new_content)
    diffs = []
    for sec, nv in new.items():
        ov = old.get(sec, "")
        if not ov and nv:
            diffs.append(f"{sec}: (empty→{len(nv)}c)")
        elif ov and nv and ov != nv:
            diffs.append(f"{sec}: ({len(ov)}c→{len(nv)}c)")
    return " | ".join(diffs[:5]) if diffs else "no section differences"


def _normalize_title(title: str) -> str:
    """Normalize a title for similarity comparison."""
    cleaned = title or ""
    cleaned = re.sub(
        r"^(Article|Literature|Concept|Topic|Project|MOC)\s*[-–—]?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s\d{4}-\d{2}-\d{2}$", "", cleaned)
    cleaned = re.sub(r"[^\w\s\u4e00-\u9fff]", "", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned.lower().strip()


def _check_duplicate(vault: Path, note_type: str, title: str) -> Path | None:
    """Return an existing similar note for article writes, if any."""
    if note_type != "article":
        return None
    import difflib

    target_dir = vault / NOTE_CONFIG[note_type]["target"]
    if not target_dir.exists():
        return None

    candidate = _normalize_title(title)
    for existing in target_dir.glob("*.md"):
        existing_norm = _normalize_title(existing.stem)
        ratio = difflib.SequenceMatcher(None, candidate, existing_norm).ratio()
        if ratio >= 0.8:
            return existing
    return None


# ---------------------------------------------------------------------------
# Index maintenance
# ---------------------------------------------------------------------------

_INDEX_FILE = "_index.md"
_LOG_FILE = "_log.md"
_LOG_ARCHIVE_FILE = "_log.archive.md"
_CORRECTIONS_FILE = "_corrections.jsonl"
_EVENTS_FILE = "_events.jsonl"
_MAX_LOG_ENTRIES = 500

_INDEX_DIRS = [
    ("02-Projects", "Projects"),
    ("03-Knowledge/Topics", "Topics"),
    ("03-Knowledge/MOCs", "MOCs"),
    ("03-Knowledge/Concepts", "Concepts"),
    ("03-Knowledge/Literature", "Literature"),
    ("06-Articles", "Articles"),
]

_SUPPORTING_SECTION_TITLE = "# Supporting notes"
_SOURCES_SECTION_TITLE = "# Sources"
_CONFLICTS_SECTION_TITLE = "# Conflicts"
_TOPIC_CASCADE_FIELDS = {"主题说明", "核心问题", "重要资料", "相关项目", "当前结论", "未解决问题"}
_NOTE_TYPES_REQUIRING_RELATION_EXTRACT = {"literature", "concept", "topic", "project"}


def _index_entry(note_path: Path, vault: Path) -> str:
    """Return a single index line for a note."""
    fm = _parse_frontmatter(
        note_path.read_text(encoding="utf-8", errors="replace")
    )
    summary = (
        fm.get("主题说明") or fm.get("一句话定义") or fm.get("解决的问题") or ""
    ).strip()
    updated = fm.get("updated", "")
    parts = [f"- [[{note_path.stem}]]"]
    if summary:
        parts.append(f" — {summary[:60]}")
    if updated:
        parts.append(f" ({updated})")
    return "".join(parts)


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _split_log_entries(text: str) -> tuple[str, list[str]]:
    """Split a markdown log file into header text and individual entries."""
    marker = "\n## ["
    if marker not in text:
        return text.rstrip("\n"), []
    start = text.index(marker)
    header = text[:start].rstrip("\n")
    body = text[start + 1 :]
    raw_entries = body.split(marker)
    entries = []
    for i, chunk in enumerate(raw_entries):
        entry = chunk if i == 0 else f"## [{chunk}"
        entries.append(entry.strip("\n"))
    return header, [entry for entry in entries if entry]


def _append_log_entries(log_path: Path, header: str, entries: list[str]) -> None:
    """Write a markdown log file from a header and entry list."""
    _ensure_parent(log_path)
    text = header.rstrip("\n")
    if entries:
        text += "\n\n" + "\n\n".join(entry.strip("\n") for entry in entries) + "\n"
    else:
        text += "\n"
    log_path.write_text(text, encoding="utf-8")


def _rotate_operation_log(vault: Path) -> None:
    """Rotate older operation-log entries into an archive file."""
    log_path = vault / _LOG_FILE
    if not log_path.exists():
        return

    header, entries = _split_log_entries(
        log_path.read_text(encoding="utf-8", errors="replace")
    )
    if len(entries) <= _MAX_LOG_ENTRIES:
        return

    archive_path = vault / _LOG_ARCHIVE_FILE
    overflow = entries[:-_MAX_LOG_ENTRIES]
    kept = entries[-_MAX_LOG_ENTRIES:]

    if archive_path.exists():
        archive_header, archive_entries = _split_log_entries(
            archive_path.read_text(encoding="utf-8", errors="replace")
        )
    else:
        archive_header, archive_entries = ("# Vault Operation Log Archive", [])

    archive_entries.extend(overflow)
    _append_log_entries(archive_path, archive_header, archive_entries)
    _append_log_entries(log_path, header or "# Vault Operation Log", kept)


def append_correction_events(vault: Path, events: list[dict]) -> Path | None:
    """Append lint findings as JSONL correction events."""
    if not events:
        return None

    corrections_path = vault / _CORRECTIONS_FILE
    _ensure_parent(corrections_path)
    with corrections_path.open("a", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return corrections_path


def append_jsonl_events(path: Path, events: list[dict]) -> Path | None:
    """Append structured events to a JSONL file."""
    if not events:
        return None

    _ensure_parent(path)
    with path.open("a", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


def append_suggestion_feedback(
    vault: Path,
    suggestion_type: str,
    action: str,
    source_note: str,
    target_notes: list[str],
    reason: str = "",
) -> Path:
    """Append a structured suggestion-feedback event and mirror it to the log."""
    normalized_targets = []
    for target in target_notes:
        normalized = _normalize_feedback_target(target)
        if normalized:
            normalized_targets.append(normalized)

    event = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "event_type": "suggestion_feedback",
        "suggestion_type": suggestion_type,
        "source_note": source_note,
        "target_notes": normalized_targets,
        "action": action,
        "reason": reason,
    }
    events_path = vault / _EVENTS_FILE
    append_jsonl_events(events_path, [event])
    session = _safe_session_memory(vault)
    if session is not None and action in {"reject", "modify-accept"}:
        for target in normalized_targets:
            try:
                session.reject_target(source_note, target)
            except Exception:
                continue

    details = [
        f"Suggestion type: {suggestion_type}",
        f"Action: {action}",
        f"Targets: {', '.join(normalized_targets) if normalized_targets else '(none)'}",
    ]
    if reason:
        details.append(f"Reason: {reason}")
    append_operation_log(vault, "suggestion-feedback", source_note, details)
    return events_path


def _maybe_emit_orphan_correction(
    vault: Path,
    filepath: Path,
    suggestions: list,
    is_draft: bool,
) -> None:
    """Emit an orphan-on-create correction if the note has no topic parent."""
    if is_draft:
        return
    # Only apply to notes inside 03-Knowledge (not daily notes, inbox, archive)
    try:
        rel = filepath.relative_to(vault)
    except ValueError:
        return
    if rel.parts[0] != "03-Knowledge":
        return

    has_topic = any("Topics" in str(rel) for rel, _ in suggestions)
    if not has_topic:
        append_correction_events(
            vault,
            [
                {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "note": str(rel),
                    "issue_type": "orphan-on-create",
                    "detail": "no topic parent at creation time",
                    "detected_by": "write",
                    "resolved": False,
                }
            ],
        )
        print("[Orphan warning] This note has no topic parent. Consider attaching it to a topic.")


def _print_feedback_hint(
    source_note: str, suggestion_type: str, targets: list[str], reason: str = ""
) -> None:
    """Print a copyable feedback command hint for suggestion-producing flows."""
    if not source_note or not suggestion_type:
        return

    script = Path(__file__).resolve()
    normalized_targets = []
    for target in targets:
        normalized = _normalize_feedback_target(target)
        if normalized:
            normalized_targets.append(normalized)
    joined_targets = ",".join(normalized_targets)
    print("\n[Feedback hint]")
    print("  Record a rejection or modified acceptance with:")
    print(
        f"  python \"{script}\" "
        f"--type suggestion-feedback --source-note \"{source_note}\" "
        f"--suggestion-type {suggestion_type} --feedback-action reject|modify-accept "
        f"--targets \"{joined_targets}\""
    )
    if reason:
        print(f"  Reason: {reason}")


def append_operation_log(
    vault: Path,
    operation: str,
    title: str = "",
    details: list[str] | None = None,
) -> Path:
    """Append an operation entry to the vault log."""
    log_path = vault / _LOG_FILE
    _ensure_parent(log_path)
    if not log_path.exists():
        log_path.write_text("# Vault Operation Log\n", encoding="utf-8")

    lines = ["", f"## [{_today_str()}] {operation}"]
    if title:
        lines[0] = ""
        lines[1] = f"## [{_today_str()}] {operation} | {title}"
    for detail in details or []:
        lines.append(f"- {detail}")

    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    _rotate_operation_log(vault)
    return log_path


def _append_bullet_to_section(text: str, section_title: str, bullet: str) -> str:
    """Append a bullet under a markdown section, creating the section if needed."""
    bullet_line = f"- {bullet}"
    if bullet_line in text:
        return text

    lines = text.splitlines(keepends=True)
    insert_at = len(lines)
    in_section = False
    for i, line in enumerate(lines):
        if line.strip() == section_title:
            in_section = True
            continue
        if in_section and line.startswith("# "):
            insert_at = i
            break

    if in_section:
        prefix = "" if insert_at == 0 or (insert_at > 0 and lines[insert_at - 1].endswith("\n")) else "\n"
        lines.insert(insert_at, prefix + bullet_line + "\n")
        return "".join(lines)

    text = text.rstrip("\n")
    return f"{text}\n\n{section_title}\n{bullet_line}\n"


def add_supporting_note(note_path: Path, supporting_note_stem: str) -> bool:
    """Add a supporting-note bullet if it is not already present."""
    text = note_path.read_text(encoding="utf-8", errors="replace")
    updated = _append_bullet_to_section(
        text, _SUPPORTING_SECTION_TITLE, f"[[{supporting_note_stem}]]"
    )
    if updated == text:
        return False
    note_path.write_text(updated, encoding="utf-8")
    return True


def add_source_reference(note_path: Path, source_label: str) -> bool:
    """Add a source reference bullet if it is not already present."""
    text = note_path.read_text(encoding="utf-8", errors="replace")
    updated = _append_bullet_to_section(text, _SOURCES_SECTION_TITLE, source_label)
    if updated == text:
        return False
    note_path.write_text(updated, encoding="utf-8")
    return True


def add_conflict_annotation(
    note_path: Path,
    source_note: str,
    claim: str,
    conflicts_with: str,
    status: str = "unresolved",
) -> bool:
    """Append a conflict entry under # Conflicts if it is not already present."""
    source_line = f"Source: [[{source_note}]]"
    claim_line = f"Claim: {claim.strip()}"
    conflicts_line = f"Conflicts with: {conflicts_with.strip()}"
    status_line = f"Status: {status.strip() or 'unresolved'}"
    block = "\n".join(
        [
            source_line,
            claim_line,
            conflicts_line,
            status_line,
        ]
    )

    text = note_path.read_text(encoding="utf-8", errors="replace")
    if block in text:
        return False

    updated = _append_bullet_to_section(
        text,
        _CONFLICTS_SECTION_TITLE,
        f"{source_line}\n  {claim_line}\n  {conflicts_line}\n  {status_line}",
    )
    if updated == text:
        return False
    note_path.write_text(updated, encoding="utf-8")
    return True


def update_note_sections(note_path: Path, fields: dict) -> list[str]:
    """Replace or append top-level markdown sections from fields."""
    if not fields:
        return []

    text = note_path.read_text(encoding="utf-8", errors="replace")
    changed_sections = []

    for key, value in fields.items():
        section_title = f"# {key}"
        replacement = str(value).strip()
        pattern = rf"(?ms)^# {re.escape(key)}\n(.*?)(?=^# |\Z)"
        replacement_block = f"{section_title}\n{replacement}\n\n"
        new_text, count = re.subn(pattern, replacement_block, text)
        if count:
            if new_text != text:
                text = new_text
                changed_sections.append(key)
            continue

        if text.endswith("\n"):
            text = text.rstrip("\n")
        text = f"{text}\n\n{section_title}\n{replacement}\n"
        changed_sections.append(key)

    note_path.write_text(text, encoding="utf-8")
    return changed_sections


def find_merge_candidates(vault: Path, title: str, limit: int = 5) -> list[Path]:
    """Return likely literature merge candidates based on title keywords."""
    literature_dir = vault / "03-Knowledge/Literature"
    if not literature_dir.exists():
        return []

    keywords = [word.lower() for word in _suggestion_keywords_from_stem(title)]
    if not keywords:
        keywords = [word.lower() for word in re.split(r"[\s\-_]+", title) if len(word) >= 4]
    if not keywords:
        return []

    scored = []
    for md_file in literature_dir.glob("*.md"):
        stem = md_file.stem.lower()
        try:
            body = md_file.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            body = ""
        title_hits = sum(1 for kw in keywords if kw in stem)
        body_hits = sum(1 for kw in keywords if kw in body)
        score = title_hits * 2 + body_hits
        if score > 0:
            scored.append((score, md_file))

    scored.sort(key=lambda item: (-item[0], str(item[1])))
    return [path for _, path in scored[:limit]]


def find_cascade_candidates(vault: Path, note_path: Path, limit: int = 3) -> list[tuple[Path, str]]:
    """Return likely topic notes for narrow cascade updates."""
    suggestions = suggest_links(vault, note_path)
    candidates = []
    for rel, reason in suggestions:
        rel_path = Path(rel)
        if "Topics" not in rel_path.parts:
            continue
        candidates.append((vault / rel_path, reason))
    return candidates[:limit]


def _resolve_vault_path(vault: Path, target_arg: str) -> Path:
    path = Path(target_arg)
    if not path.is_absolute():
        path = vault / path
    return path


def run_ingest_sync(vault: Path, target_path: Path, plan: dict) -> dict:
    """Apply a deterministic ingest plan in one shot.

    Expected plan shape:
    {
      "primary_fields": {...},
      "source_note": "...",
      "source_ref": "...",
      "cascade_updates": [{"target": "...", "fields": {...}, "source_note": "..."}],
      "conflicts": [{"target": "...", "claim": "...", "conflicts_with": "...", "source_note": "...", "status": "..."}]
    }
    """
    if not target_path.exists():
        raise FileNotFoundError(f"target note not found: {target_path}")

    summary = {
        "primary_updates": [],
        "cascade_updates": [],
        "conflicts": [],
    }

    primary_fields = plan.get("primary_fields") or {}
    source_note = (plan.get("source_note") or "").strip()
    source_ref = (plan.get("source_ref") or "").strip()
    primary_changes = []
    changed_sections = update_note_sections(target_path, primary_fields)
    if changed_sections:
        primary_changes.append(f"Sections updated: {', '.join(changed_sections)}")
    if source_note and add_supporting_note(target_path, source_note):
        primary_changes.append(f"Supporting note: [[{source_note}]]")
    if source_ref and add_source_reference(target_path, source_ref):
        primary_changes.append(f"Source added: {source_ref}")
    if primary_changes:
        touch_updated(target_path)
        primary_changes.append(f"Updated date: {_today_str()}")
        _record_session_note(vault, "topic" if "Topics" in target_path.parts else "note", target_path)
    summary["primary_updates"] = primary_changes

    for cascade in plan.get("cascade_updates") or []:
        cascade_target = _resolve_vault_path(vault, cascade.get("target", ""))
        if not cascade_target.exists():
            raise FileNotFoundError(f"cascade target not found: {cascade_target}")
        cascade_fields = cascade.get("fields") or {}
        invalid = [key for key in cascade_fields if key not in _TOPIC_CASCADE_FIELDS]
        if invalid:
            raise ValueError(
                f"cascade-update only supports topic fields: {', '.join(invalid)}"
            )
        cascade_note = (cascade.get("source_note") or source_note).strip()
        cascade_changes = []
        changed_sections = update_note_sections(cascade_target, cascade_fields)
        if changed_sections:
            cascade_changes.append(f"Sections updated: {', '.join(changed_sections)}")
        if cascade_note and add_supporting_note(cascade_target, cascade_note):
            cascade_changes.append(f"Supporting note: [[{cascade_note}]]")
        if cascade_changes:
            touch_updated(cascade_target)
            cascade_changes.append(f"Updated date: {_today_str()}")
            _record_session_note(vault, "topic", cascade_target)
        if cascade_changes:
            summary["cascade_updates"].append(
                {"target": str(cascade_target.relative_to(vault)), "details": cascade_changes}
            )

    for conflict in plan.get("conflicts") or []:
        conflict_target = _resolve_vault_path(vault, conflict.get("target", ""))
        if not conflict_target.exists():
            raise FileNotFoundError(f"conflict target not found: {conflict_target}")
        conflict_source = (conflict.get("source_note") or source_note).strip()
        claim = (conflict.get("claim") or "").strip()
        conflicts_with = (conflict.get("conflicts_with") or "").strip()
        status = (conflict.get("status") or "unresolved").strip()
        if not conflict_source or not claim or not conflicts_with:
            raise ValueError("conflict entries require source_note, claim, and conflicts_with")
        changed = add_conflict_annotation(
            conflict_target,
            conflict_source,
            claim,
            conflicts_with,
            status,
        )
        details = [
            f"Conflict source: [[{conflict_source}]]",
            f"Conflicts with: {conflicts_with}",
            f"Status: {status}",
        ]
        if changed:
            touch_updated(conflict_target)
            details.insert(0, "Conflict added")
            details.append(f"Updated date: {_today_str()}")
            _record_session_note(vault, "topic" if "Topics" in conflict_target.parts else "note", conflict_target)
        else:
            details.insert(0, "Conflict already present")
        summary["conflicts"].append(
            {"target": str(conflict_target.relative_to(vault)), "details": details}
        )

    log_details = []
    if summary["primary_updates"]:
        log_details.append(f"Primary target: {target_path.relative_to(vault)}")
        log_details.extend(summary["primary_updates"])
    for cascade in summary["cascade_updates"]:
        log_details.append(f"Cascade-updated: {cascade['target']}")
    for conflict in summary["conflicts"]:
        log_details.append(f"Conflict-updated: {conflict['target']}")
    if not log_details:
        log_details.append("No content changes")
    append_operation_log(vault, "ingest-sync", target_path.stem, log_details)
    return summary


def rebuild_index(vault: Path) -> Path:
    """Rebuild _index.md from scratch by scanning all managed directories."""
    today = date.today().strftime("%Y-%m-%d")
    lines = [
        "---",
        "type: index",
        f"updated: {today}",
        "---",
        "",
        "# Knowledge Base Index",
        "",
        f"_Last rebuilt: {today}_",
        "",
    ]

    for rel_dir, section_name in _INDEX_DIRS:
        target = vault / rel_dir
        if not target.exists():
            continue
        notes = sorted(target.glob("*.md"))
        if not notes:
            continue
        lines.append(f"## {section_name} ({len(notes)})")
        for note in notes:
            lines.append(_index_entry(note, vault))
        lines.append("")

    # Recent notes (last 7 days)
    recent_threshold = date.today() - timedelta(days=7)
    recent = []
    for rel_dir, _ in _INDEX_DIRS:
        target = vault / rel_dir
        if not target.exists():
            continue
        for note in target.glob("*.md"):
            fm = _parse_frontmatter(
                note.read_text(encoding="utf-8", errors="replace")
            )
            updated_str = fm.get("updated", "")
            if updated_str:
                try:
                    if date.fromisoformat(updated_str) >= recent_threshold:
                        recent.append((updated_str, note.stem))
                except ValueError:
                    pass

    if recent:
        recent.sort(reverse=True)
        lines.append("## Recent (last 7 days)")
        for updated, stem in recent[:10]:
            lines.append(f"- {updated}: [[{stem}]]")
        lines.append("")

    index_path = vault / _INDEX_FILE
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def _append_to_index(vault: Path, note_path: Path, section_name: str) -> None:
    """Incrementally add a new note entry to the relevant section in _index.md."""
    index_path = vault / _INDEX_FILE
    if not index_path.exists():
        rebuild_index(vault)
        return

    text = index_path.read_text(encoding="utf-8")
    # Already listed?
    if note_path.stem in text:
        return

    entry = _index_entry(note_path, vault)
    header = f"## {section_name}"
    if header in text:
        # Insert after the section header (before the next blank line or section)
        lines = text.splitlines(keepends=True)
        insert_at = len(lines)
        in_section = False
        for i, line in enumerate(lines):
            if line.strip() == header:
                in_section = True
                continue
            if in_section and (line.startswith("## ") or line.strip() == ""):
                insert_at = i
                break
        lines.insert(insert_at, entry + "\n")
        index_path.write_text("".join(lines), encoding="utf-8")
    else:
        # Section missing — full rebuild
        rebuild_index(vault)


# ---------------------------------------------------------------------------
# Lint helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter as a plain key:value dict."""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    result = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result


def _set_frontmatter_field(text: str, key: str, value: str) -> str:
    """Set or insert a simple frontmatter field."""
    if not text.startswith("---"):
        return text
    end = text.find("---", 3)
    if end == -1:
        return text

    pattern = rf"(?m)^({re.escape(key)}:\s*).*$"
    fm_block = text[:end]
    rest = text[end:]
    if re.search(pattern, fm_block):
        fm_block = re.sub(pattern, lambda m: f"{m.group(1)}{value}", fm_block)
    else:
        fm_block = fm_block.rstrip("\n") + f"\n{key}: {value}\n"
    return fm_block + rest


def touch_updated(note_path: Path) -> bool:
    """Refresh the updated frontmatter field to today."""
    text = note_path.read_text(encoding="utf-8", errors="replace")
    new_text = _set_frontmatter_field(text, "updated", _today_str())
    if new_text == text:
        return False
    note_path.write_text(new_text, encoding="utf-8")
    return True


def _extract_wikilinks(text: str) -> set:
    """Return all wikilink targets from text, normalized to stem only.

    Obsidian resolves [[folder/Note]] by stem, so we strip any path prefix
    to avoid false-positive broken-link reports.
    """
    pattern = r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]"
    stems = set()
    for m in re.finditer(pattern, text):
        target = m.group(1).strip()
        # Strip folder prefix: [[03-Knowledge/Topics/Foo]] → "Foo"
        stem = target.rsplit("/", 1)[-1]
        stems.add(stem)
    return stems


def _extract_section(text: str, title: str) -> str:
    """Extract a top-level markdown section body by heading title."""
    pattern = rf"(?ms)^# {re.escape(title)}\n(.*?)(?=^# |\Z)"
    match = re.search(pattern, text)
    if not match:
        return ""
    return match.group(1).strip()


def _query_keywords(query_text: str) -> list[str]:
    """Return meaningful query keywords shared across retrieval helpers."""
    keywords = _suggestion_keywords_from_stem(query_text)
    if keywords:
        return keywords
    return [part for part in re.split(r"[\s\-_]+", query_text) if len(part) >= 2]


def _extract_profile_section(profile_context: str, section_title: str) -> str:
    """Return a markdown subsection body from concatenated profile context."""
    pattern = rf"(?ms)^## {re.escape(section_title)}\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, profile_context)
    if not match:
        return ""
    return match.group(1).strip()


def _profile_query_keywords(profile_context: str) -> list[str]:
    """Extract lightweight query expansion keywords from profile context."""
    if not profile_context:
        return []

    blocks = []
    for section_title in ("常讨论话题", "编程语言", "工具链", "AI 行为偏好"):
        block = _extract_profile_section(profile_context, section_title)
        if block:
            blocks.append(block)

    keywords: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        for kw in _suggestion_keywords_from_stem(block):
            cleaned = kw.strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            keywords.append(cleaned)
    return keywords


def _topic_summary_payload(note_path: Path, text: str) -> dict:
    """Build the Tier 1 payload for a topic note."""
    return {
        "path": note_path,
        "title": note_path.stem,
        "主题说明": _extract_section(text, "主题说明"),
        "当前结论": _extract_section(text, "当前结论"),
        "未解决问题": _extract_section(text, "未解决问题"),
    }


def query_vault(vault: Path, query_text: str, include_details: bool = False, limit: int = 5) -> dict:
    """Query the vault with session-first, topic-first retrieval.

    Returns a structured payload:
    {
      "tier1_topics": [topic summary dicts],
      "tier2_grouped": [{"topic": "...", "notes": [..]}],
      "orphans": [note dicts],
    }
    """
    record_session_query(vault, query_text)
    profile_context = ""
    if read_profile is not None:
        try:
            profile_context = read_profile(vault).strip()
        except Exception:
            profile_context = ""
    keywords = [kw.lower() for kw in _query_keywords(query_text)]
    for kw in _profile_query_keywords(profile_context):
        lowered = kw.lower()
        if lowered not in keywords:
            keywords.append(lowered)
    topic_dir = vault / "03-Knowledge" / "Topics"
    topic_payloads: list[tuple[int, dict]] = []
    seen_topics: set[Path] = set()

    for session_path in find_session_relevant_notes(vault, query_text, limit=limit):
        if session_path.parent != topic_dir:
            continue
        try:
            text = session_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        haystack = " ".join(
            filter(
                None,
                [
                    session_path.stem.lower(),
                    _extract_section(text, "主题说明").lower(),
                    _extract_section(text, "当前结论").lower(),
                    _extract_section(text, "未解决问题").lower(),
                ],
            )
        )
        overlap = sum(1 for kw in keywords if kw in haystack)
        if keywords and overlap == 0:
            continue
        topic_payloads.append((100 + overlap * 10, _topic_summary_payload(session_path, text)))
        seen_topics.add(session_path)

    if topic_dir.exists():
        for topic_path in topic_dir.glob("*.md"):
            if topic_path in seen_topics:
                continue
            try:
                text = topic_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            haystack = " ".join(
                filter(
                    None,
                    [
                        topic_path.stem.lower(),
                        _extract_section(text, "主题说明").lower(),
                        _extract_section(text, "当前结论").lower(),
                        _extract_section(text, "未解决问题").lower(),
                    ],
                )
            )
            overlap = sum(1 for kw in keywords if kw in haystack)
            if keywords and overlap == 0:
                continue
            topic_payloads.append((overlap * 10, _topic_summary_payload(topic_path, text)))

    topic_payloads.sort(key=lambda item: (-item[0], item[1]["title"]))
    tier1_topics = [payload for _, payload in topic_payloads[:limit]]
    if tier1_topics and not include_details:
        for item in tier1_topics:
            _record_session_note(vault, "topic", item["path"])
        return {
            "tier1_topics": tier1_topics,
            "tier2_grouped": [],
            "orphans": [],
            "profile_context": profile_context,
        }

    detail_dirs = [
        vault / "03-Knowledge" / "Literature",
        vault / "03-Knowledge" / "Concepts",
        vault / "02-Projects",
        vault / "06-Articles",
    ]
    grouped: dict[str, list[dict]] = {}
    orphans: list[dict] = []
    topic_titles = {item["title"] for item in tier1_topics}

    for detail_dir in detail_dirs:
        if not detail_dir.exists():
            continue
        for note_path in detail_dir.glob("*.md"):
            try:
                text = note_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            haystack = text.lower()
            overlap = sum(1 for kw in keywords if kw in note_path.stem.lower() or kw in haystack)
            if keywords and overlap == 0:
                continue

            note_item = {
                "path": note_path,
                "title": note_path.stem,
                "excerpt": (
                    _extract_section(text, "核心观点")
                    or _extract_section(text, "方法要点")
                    or _extract_section(text, "一句话定义")
                    or _extract_section(text, "项目描述")
                )[:200],
            }
            links = _extract_wikilinks(text)
            parent_topics = sorted(link for link in links if link.startswith("Topic - "))
            if not parent_topics:
                orphans.append(note_item)
                continue
            matched_parent = next((topic for topic in parent_topics if topic in topic_titles), parent_topics[0])
            grouped.setdefault(matched_parent, []).append(note_item)

    tier2_grouped = [
        {"topic": topic, "notes": notes[:limit]}
        for topic, notes in sorted(grouped.items(), key=lambda item: item[0])
    ]
    for item in tier1_topics:
        _record_session_note(vault, "topic", item["path"])
    for group in tier2_grouped:
        for note in group["notes"]:
            _record_session_note(vault, "note", note["path"])
    for note in orphans[:limit]:
        _record_session_note(vault, "note", note["path"])
    return {
        "tier1_topics": tier1_topics,
        "tier2_grouped": tier2_grouped,
        "orphans": orphans[:limit],
        "profile_context": profile_context,
    }


def organize_vault(vault: Path, query_text: str, limit: int = 10) -> dict:
    """Return a session-first organization view for related notes.

    The result is intended to drive `/obsidian organize` style workflows:
    - surface current-session notes first
    - find related notes across knowledge + inbox
    - suggest whether the result should converge into a topic or a MOC
    """
    record_session_query(vault, query_text)
    profile_context = ""
    if read_profile is not None:
        try:
            profile_context = read_profile(vault).strip()
        except Exception:
            profile_context = ""
    keywords = [kw.lower() for kw in _query_keywords(query_text)]
    for kw in _profile_query_keywords(profile_context):
        lowered = kw.lower()
        if lowered not in keywords:
            keywords.append(lowered)
    session_hits = find_session_relevant_notes(vault, query_text, limit=min(limit, 5))
    candidate_dirs = [
        vault / "03-Knowledge",
        vault / "00-Inbox",
        vault / "06-Articles",
    ]
    matches: list[tuple[int, dict]] = []
    seen_paths = {path.resolve() for path in session_hits}

    for root in candidate_dirs:
        if not root.exists():
            continue
        for note_path in root.rglob("*.md"):
            try:
                text = note_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            overlap = sum(
                1 for kw in keywords
                if kw in note_path.stem.lower() or kw in text.lower()
            )
            if keywords and overlap == 0:
                continue
            rel = note_path.relative_to(vault)
            note_type = _parse_frontmatter(text).get("type", "")
            parent_topics = sorted(link for link in _extract_wikilinks(text) if link.startswith("Topic - "))
            note_item = {
                "path": note_path,
                "title": note_path.stem,
                "relative_path": str(rel),
                "type": note_type,
                "excerpt": (
                    _extract_section(text, "当前结论")
                    or _extract_section(text, "核心观点")
                    or _extract_section(text, "一句话定义")
                    or _extract_section(text, "项目描述")
                )[:200],
                "in_session": note_path.resolve() in seen_paths,
                "in_inbox": rel.parts[0] == "00-Inbox",
                "parent_topics": parent_topics,
            }
            base = 100 if note_item["in_session"] else 0
            if note_type == "topic":
                base += 20
            matches.append((base + overlap * 10, note_item))

    matches.sort(key=lambda item: (-item[0], item[1]["relative_path"]))
    selected = [item for _, item in matches[:limit]]

    topic_match_count = sum(1 for item in selected if item["type"] == "topic")
    source_match_count = sum(
        1 for item in selected if item["type"] in {"literature", "concept", "project"}
    )
    orphan_match_count = sum(
        1 for item in selected
        if item["type"] in {"literature", "concept", "project"} and not item["parent_topics"]
    )
    inbox_match_count = sum(1 for item in selected if item["in_inbox"])
    session_match_count = sum(1 for item in selected if item["in_session"])

    reasons: list[str] = []
    topic_score = 0
    moc_score = 0

    if topic_match_count:
        topic_score += 3
        reasons.append(f"{topic_match_count} existing topic match(es) found")
    if orphan_match_count >= 2:
        topic_score += 3
        reasons.append(f"{orphan_match_count} orphan source note(s) suggest fragmentation")
    elif orphan_match_count == 1:
        topic_score += 1
        reasons.append("1 orphan source note may need a clearer topic home")
    if session_match_count:
        topic_score += 2
        reasons.append(f"{session_match_count} match(es) are active in the current session")
    if inbox_match_count:
        topic_score += 1
        reasons.append(f"{inbox_match_count} inbox note(s) are waiting to be organized")
    if source_match_count >= 2:
        topic_score += 1
        reasons.append(f"{source_match_count} source note(s) share the current subject")

    if topic_match_count == 0 and len(selected) <= 1:
        moc_score += 3
        reasons.append("only a shallow cluster was found")
    if topic_match_count == 0 and orphan_match_count == 0 and source_match_count <= 1:
        moc_score += 2
        reasons.append("no strong topic-level synthesis target exists yet")
    if len(selected) == 1:
        moc_score += 1

    if not selected:
        suggestion = "none"
        confidence = "low"
        reasons = ["no related notes found"]
    else:
        suggestion = "topic" if topic_score >= moc_score else "moc"
        score_gap = abs(topic_score - moc_score)
        if score_gap >= 3:
            confidence = "high"
        elif score_gap >= 1:
            confidence = "medium"
        else:
            confidence = "low"

    synthetic_path = Path(f"03-Knowledge/Literature/Literature - {query_text}.md")
    link_suggestions = suggest_links(vault, vault / synthetic_path)
    new_topic_hint = suggest_new_topic(synthetic_path, link_suggestions)

    for item in selected:
        _record_session_note(vault, "topic" if item["type"] == "topic" else "note", item["path"])

    return {
        "session_hits": session_hits,
        "matches": selected,
        "suggested_output": suggestion,
        "confidence": confidence,
        "reasons": reasons,
        "new_topic_hint": new_topic_hint,
        "profile_context": profile_context,
    }


def _fix_frontmatter(text: str, path: Path, fm: dict) -> tuple:
    """Add missing required frontmatter fields. Return (new_text, list_of_fixes)."""
    today = date.today().strftime("%Y-%m-%d")
    defaults = {
        "status": "active",
        "created": today,
        "updated": today,
        "reviewed": "false",
    }
    missing = {k: v for k, v in defaults.items() if k not in fm}
    if not missing:
        return text, []

    # Insert missing keys before the closing ---
    end = text.find("---", 3)
    if end == -1:
        # Malformed frontmatter: no closing ---; do not attempt repair
        return text, [f"{path.name}: skipped auto-fix (malformed frontmatter, no closing ---)"]
    insert_lines = "".join(f"{k}: {v}\n" for k, v in missing.items())
    new_text = text[:end] + insert_lines + text[end:]
    fixes = [f"{path.name}: added missing frontmatter field(s): {', '.join(missing)}"]
    return new_text, fixes


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

_INBOX_BACKLOG_DAYS = 7
_STALE_DAYS = 90
_STALE_SYNTHESIS_DAYS = 30   # topic synthesis lag threshold relative to linked literature
_SKELETON_RATIO = 0.5   # fraction of _待补充_ sections that triggers "skeleton"

_SKIP_LINT_DIRS = {"01-DailyNotes", "04-Archive", "Templates", "Attachments"}
_KNOWLEDGE_DIRS = {"02-Projects", "03-Knowledge"}


def lint_vault(vault: Path, auto_fix: bool = False) -> None:
    """Scan vault for quality issues, optionally auto-fix simple ones."""
    all_notes = list(vault.rglob("*.md"))
    note_stems = {f.stem for f in all_notes}

    # Read all note contents once
    contents: dict[Path, str] = {}
    for f in all_notes:
        try:
            contents[f] = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            contents[f] = ""

    today = date.today()
    auto_fixes = []
    broken: list[str] = []
    orphans: list[str] = []
    inbox_backlog: list[str] = []
    stale_synthesis: list[str] = []
    skeletons: list[str] = []
    stale: list[str] = []
    correction_events: list[dict] = []

    # Build set of all referenced note stems across all files
    referenced: set = set()
    for text in contents.values():
        for link in _extract_wikilinks(text):
            referenced.add(link)

    def add_correction(note_path: Path, issue_type: str, detail: str) -> None:
        correction_events.append(
            {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "note": str(note_path.relative_to(vault)),
                "issue_type": issue_type,
                "detail": detail,
                "detected_by": "lint",
                "resolved": False,
            }
        )

    for note_path, text in contents.items():
        rel = note_path.relative_to(vault)
        top_dir = rel.parts[0] if rel.parts else ""
        fm = _parse_frontmatter(text)

        # --- Auto-fix: missing frontmatter fields ---
        if auto_fix and text.startswith("---"):
            new_text, fixes = _fix_frontmatter(text, note_path, fm)
            if fixes:
                note_path.write_text(new_text, encoding="utf-8")
                contents[note_path] = new_text
                text = new_text
                fm = _parse_frontmatter(new_text)
                auto_fixes.extend(fixes)

        if text.startswith("---"):
            missing_frontmatter = [
                key for key in ("status", "created", "updated", "reviewed")
                if key not in fm
            ]
            if missing_frontmatter:
                add_correction(
                    note_path,
                    "missing-frontmatter",
                    f"missing field(s): {', '.join(missing_frontmatter)}",
                )

        # --- Broken wikilinks ---
        broken_here = [
            lnk for lnk in _extract_wikilinks(text)
            if lnk and lnk not in note_stems
        ]
        for lnk in broken_here:
            broken.append(f"  {rel} → [[{lnk}]]")
            add_correction(note_path, "broken-link", f"[[{lnk}]]")

        if top_dir in _SKIP_LINT_DIRS:
            continue

        # --- Orphan notes (Knowledge + Projects, not referenced anywhere) ---
        if top_dir in _KNOWLEDGE_DIRS and note_path.stem not in referenced:
            orphans.append(f"  {rel}")
            add_correction(note_path, "orphan", "not referenced from any note")

        # --- Inbox backlog ---
        if top_dir == "00-Inbox":
            created_str = fm.get("created", "")
            if created_str:
                try:
                    age = (today - date.fromisoformat(created_str)).days
                    if age > _INBOX_BACKLOG_DAYS:
                        inbox_backlog.append(f"  {rel} ({age} days old)")
                        add_correction(note_path, "inbox-backlog", f"{age} days old")
                except ValueError:
                    pass

        # --- Skeleton notes ---
        sections = re.split(r"^#+\s.*$", text, flags=re.MULTILINE)
        section_count = len(sections) - 1  # exclude preamble
        empty_count = sum(1 for s in sections[1:] if not s.strip())
        if section_count > 0 and empty_count / section_count > _SKELETON_RATIO:
            skeletons.append(
                f"  {rel} ({empty_count}/{section_count} sections empty)"
            )
            add_correction(
                note_path,
                "skeleton",
                f"{empty_count}/{section_count} sections empty",
            )

        # --- Stale notes (active, not updated in 90+ days) ---
        if fm.get("status") == "active":
            updated_str = fm.get("updated", "")
            if updated_str:
                try:
                    age = (today - date.fromisoformat(updated_str)).days
                    if age > _STALE_DAYS:
                        stale.append(f"  {rel} ({age} days since update)")
                        add_correction(note_path, "stale", f"{age} days since update")
                except ValueError:
                    pass

    # --- Stale synthesis: topic updated lag behind linked literature ---
    topic_dir = vault / "03-Knowledge" / "Topics"
    if topic_dir.exists():
        for topic_path, topic_text in contents.items():
            if topic_path.parent != topic_dir:
                continue
            topic_fm = _parse_frontmatter(topic_text)
            topic_updated_str = topic_fm.get("updated", "")
            if not topic_updated_str:
                continue
            try:
                topic_updated = date.fromisoformat(topic_updated_str)
            except ValueError:
                continue

            # Find linked literature notes via wikilinks in the topic body
            linked_stems = _extract_wikilinks(topic_text)
            lagging: list[str] = []
            for stem in linked_stems:
                # Look up the actual file for this stem
                linked_file = next(
                    (f for f in all_notes if f.stem == stem), None
                )
                if linked_file is None:
                    continue
                linked_fm = _parse_frontmatter(contents.get(linked_file, ""))
                linked_updated_str = linked_fm.get("updated", "")
                if not linked_updated_str:
                    continue
                try:
                    linked_updated = date.fromisoformat(linked_updated_str)
                except ValueError:
                    continue
                lag = (linked_updated - topic_updated).days
                if lag > _STALE_SYNTHESIS_DAYS:
                    lagging.append(f"{stem} (+{lag}d)")

            if lagging:
                rel = topic_path.relative_to(vault)
                detail = f"linked notes updated after topic: {', '.join(lagging[:3])}"
                stale_synthesis.append(
                    f"  {rel} — {detail}"
                )
                add_correction(topic_path, "stale-synthesis", detail)

    # --- Print report ---
    total = len(all_notes)
    print(f"[Lint] Scanned {total} note(s) in {vault}\n")

    if auto_fixes:
        print(f"[Auto-fixed] ({len(auto_fixes)})")
        for f in auto_fixes:
            print(f"  ✓ {f}")
        print()

    sections = [
        ("[Broken links]", broken),
        ("[Orphan notes] (not referenced from any MOC/Topic)", orphans),
        ("[Inbox backlog] (stuck >7 days)", inbox_backlog),
        ("[Skeleton notes] (>50% fields empty)", skeletons),
        ("[Stale notes] (not updated in 90+ days)", stale),
        (f"[Stale synthesis] (topic synthesis lags linked notes by >{_STALE_SYNTHESIS_DAYS}d)", stale_synthesis),
    ]
    found_issues = False
    for header, items in sections:
        if items:
            found_issues = True
            print(f"{header} ({len(items)})")
            for item in items:
                print(f"⚠{item}")
            print()

    if not found_issues and not auto_fixes:
        print("✓ No issues found.")

    corrections_path = append_correction_events(vault, correction_events)

    issue_count = sum(len(items) for _, items in sections)
    log_details = [
        f"Broken links: {len(broken)}",
        f"Orphans: {len(orphans)}",
        f"Inbox backlog: {len(inbox_backlog)}",
        f"Skeleton notes: {len(skeletons)}",
        f"Stale notes: {len(stale)}",
        f"Stale synthesis: {len(stale_synthesis)}",
        f"Auto-fixed: {len(auto_fixes)}",
        f"Issues found: {issue_count}",
        f"Corrections recorded: {len(correction_events)}",
    ]
    if corrections_path is not None:
        log_details.append(f"Corrections file: {corrections_path.relative_to(vault)}")
    append_operation_log(vault, "lint", details=log_details)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Write a structured note to an Obsidian vault."
    )
    parser.add_argument(
        "--type",
        required=True,
        choices=list(NOTE_CONFIG.keys()) + ["capture", "fleeting", "init", "lint", "index", "query", "organize", "merge-candidates", "merge-update", "cascade-candidates", "cascade-update", "conflict-update", "ingest-sync", "suggestion-feedback", "topic-scout"],
        help="Note type",
    )
    parser.add_argument(
        "--auto-fix",
        action="store_true",
        help="Auto-fix simple issues (missing frontmatter fields) during lint",
    )
    parser.add_argument("--title", default="", help="Note title")
    parser.add_argument("--url", default="", help="Capture URL")
    parser.add_argument(
        "--source-note",
        default="",
        help="Existing note stem to add under # Supporting notes after writing",
    )
    parser.add_argument(
        "--source-ref",
        default="",
        help="Source label to add under # Sources after writing",
    )
    parser.add_argument(
        "--target",
        default="",
        help="Target note path for merge-update (absolute or vault-relative)",
    )
    parser.add_argument(
        "--conflicts-with",
        default="",
        help="Target note/file/link that this note conflicts with",
    )
    parser.add_argument(
        "--status-label",
        default="unresolved",
        help="Conflict status label, default unresolved",
    )
    parser.add_argument(
        "--suggestion-type",
        default="",
        help="Suggestion kind for suggestion-feedback (link/merge/cascade/topic)",
    )
    parser.add_argument(
        "--feedback-action",
        default="",
        help="Feedback action for suggestion-feedback (reject/modify-accept)",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Optional reason for suggestion-feedback",
    )
    parser.add_argument(
        "--targets",
        default="",
        help="Comma-separated target notes for suggestion-feedback",
    )
    parser.add_argument(
        "--fields",
        default="{}",
        help="JSON string of field values",
    )
    parser.add_argument(
        "--draft",
        default="false",
        choices=["true", "false"],
        help="Write to Inbox instead of target directory",
    )
    parser.add_argument(
        "--vault",
        default=str(VAULT_PATH),
        help="Path to Obsidian vault (overrides OBSIDIAN_VAULT_PATH env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print rendered content without writing to disk",
    )
    parser.add_argument(
        "--query",
        default="",
        help="Query text for --type query",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Include Tier 2 drill-down details for --type query",
    )
    return parser.parse_args(argv)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)

    try:
        fields = json.loads(args.fields)
    except json.JSONDecodeError as e:
        print(f"Error: --fields is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    vault = Path(args.vault)
    note_type = args.type

    # --- Init: special case ---
    if note_type == "init":
        init_vault(vault)
        return

    # --- Lint: special case ---
    if note_type == "lint":
        lint_vault(vault, auto_fix=args.auto_fix)
        return

    # --- Topic scout ---
    if note_type == "topic-scout":
        scout_topics(vault)
        return

    # --- Index: special case ---
    if note_type == "index":
        index_path = rebuild_index(vault)
        print(f"[OK] Index rebuilt: {index_path.relative_to(vault)}")
        return

    # --- Query: special case ---
    if note_type == "query":
        query_text = args.query.strip() or args.title.strip() or str(fields.get("query", "")).strip()
        if not query_text:
            print("Error: --query is required for query", file=sys.stderr)
            sys.exit(1)
        result = query_vault(vault, query_text, include_details=args.details)
        tier1_topics = result["tier1_topics"]
        tier2_grouped = result["tier2_grouped"]
        orphans = result["orphans"]
        profile_context = result.get("profile_context", "")

        if not tier1_topics and not tier2_grouped and not orphans:
            print(f"[Query] No matches for: {query_text}")
            if profile_context:
                print("\n[Profile]")
                print(profile_context)
            return

        print(f"[Query] {query_text}")
        if profile_context:
            print("\n[Profile]")
            print(profile_context)
        if tier1_topics:
            print("\n[Tier 1: Topics]")
            for item in tier1_topics:
                print(f"  [[{item['title']}]]")
                if item["主题说明"]:
                    print(f"    主题说明: {item['主题说明']}")
                if item["当前结论"]:
                    print(f"    当前结论: {item['当前结论']}")
                if item["未解决问题"]:
                    print(f"    未解决问题: {item['未解决问题']}")
            if not args.details:
                print('\n[Hint] Use --details to include drill-down notes.')

        if tier2_grouped:
            print("\n[Tier 2: Details]")
            for group in tier2_grouped:
                print(f"  Topic: [[{group['topic']}]]")
                for note in group["notes"]:
                    excerpt = f" — {note['excerpt']}" if note["excerpt"] else ""
                    print(f"    [[{note['title']}]]{excerpt}")

        if orphans:
            print("\n[Orphans]")
            for note in orphans:
                excerpt = f" — {note['excerpt']}" if note["excerpt"] else ""
                print(f"  [[{note['title']}]]{excerpt}")
        return

    if note_type == "organize":
        query_text = args.query.strip() or args.title.strip() or str(fields.get("query", "")).strip()
        if not query_text:
            print("Error: --query is required for organize", file=sys.stderr)
            sys.exit(1)
        result = organize_vault(vault, query_text)
        matches = result["matches"]
        profile_context = result.get("profile_context", "")
        if not matches:
            print(f"[Organize] No related notes found for: {query_text}")
            if profile_context:
                print("\n[Profile]")
                print(profile_context)
            return
        print(f"[Organize] {query_text}")
        if profile_context:
            print("\n[Profile]")
            print(profile_context)
        if result["session_hits"]:
            print("\n[Session-first]")
            for path in result["session_hits"]:
                print(f"  [[{path.stem}]]")
        print("\n[Matches]")
        for item in matches:
            markers = []
            if item["in_session"]:
                markers.append("session")
            if item["in_inbox"]:
                markers.append("inbox")
            marker_text = f" ({', '.join(markers)})" if markers else ""
            excerpt = f" — {item['excerpt']}" if item["excerpt"] else ""
            print(f"  [[{item['title']}]]{marker_text}{excerpt}")
        print(
            f"\n[Suggest] Converge into: {result['suggested_output']} "
            f"(confidence={result['confidence']})"
        )
        if result["reasons"]:
            print("[Reasons]")
            for reason in result["reasons"]:
                print(f"  - {reason}")
        if result["new_topic_hint"]:
            print(f"[Topic suggestion] {result['new_topic_hint']}")
        return

    if note_type == "merge-candidates":
        title = args.title.strip()
        if not title:
            print("Error: --title is required for merge-candidates", file=sys.stderr)
            sys.exit(1)
        candidates = find_merge_candidates(vault, title)
        if not candidates:
            print("[OK] No merge candidates found.")
            return
        print("[Merge candidates]")
        for candidate in candidates:
            print(f"  -> {candidate.relative_to(vault)}")
        _print_feedback_hint(
            source_note=NOTE_CONFIG["literature"]["prefix"] + f" - {title}",
            suggestion_type="merge",
            targets=[str(candidate.relative_to(vault)) for candidate in candidates[:3]],
            reason="Use if you reject these merge candidates or pick a narrower target.",
        )
        return

    if note_type == "cascade-candidates":
        target_arg = args.target.strip()
        if not target_arg:
            print("Error: --target is required for cascade-candidates", file=sys.stderr)
            sys.exit(1)
        source_path = Path(target_arg)
        if not source_path.is_absolute():
            source_path = vault / source_path
        if not source_path.exists():
            print(f"Error: source note not found: {source_path}", file=sys.stderr)
            sys.exit(1)
        candidates = find_cascade_candidates(vault, source_path)
        if not candidates:
            print("[OK] No cascade candidates found.")
            return
        print("[Cascade candidates]")
        for candidate, reason in candidates:
            print(f"  -> {candidate.relative_to(vault)} ({reason})")
        _print_feedback_hint(
            source_note=source_path.stem,
            suggestion_type="cascade",
            targets=[str(candidate.relative_to(vault)) for candidate, _ in candidates[:3]],
            reason="Use if you reject these cascade targets or manually update a different topic.",
        )
        return

    if note_type == "merge-update":
        target_arg = args.target.strip()
        if not target_arg:
            print("Error: --target is required for merge-update", file=sys.stderr)
            sys.exit(1)
        target_path = Path(target_arg)
        if not target_path.is_absolute():
            target_path = vault / target_path
        if not target_path.exists():
            print(f"Error: target note not found: {target_path}", file=sys.stderr)
            sys.exit(1)

        changed_sections = update_note_sections(target_path, fields)
        merge_updates = []
        if changed_sections:
            merge_updates.append(f"Sections updated: {', '.join(changed_sections)}")
        if args.source_note and add_supporting_note(target_path, args.source_note):
            merge_updates.append(f"Supporting note: [[{args.source_note}]]")
        if args.source_ref and add_source_reference(target_path, args.source_ref):
            merge_updates.append(f"Source added: {args.source_ref}")
        if merge_updates and merge_updates != ["No content changes"] and touch_updated(target_path):
            merge_updates.append(f"Updated date: {_today_str()}")
        if not merge_updates:
            merge_updates.append("No content changes")

        append_operation_log(vault, "merge", target_path.stem, merge_updates)
        print(f"[OK] Merged into: {target_path.relative_to(vault)}")
        if merge_updates:
            print("\n[Merge updates]")
            for item in merge_updates:
                print(f"  -> {item}")
        return

    if note_type == "cascade-update":
        target_arg = args.target.strip()
        if not target_arg:
            print("Error: --target is required for cascade-update", file=sys.stderr)
            sys.exit(1)
        target_path = Path(target_arg)
        if not target_path.is_absolute():
            target_path = vault / target_path
        if not target_path.exists():
            print(f"Error: target note not found: {target_path}", file=sys.stderr)
            sys.exit(1)

        invalid = [key for key in fields if key not in _TOPIC_CASCADE_FIELDS]
        if invalid:
            print(
                f"Error: cascade-update only supports topic fields: {', '.join(invalid)}",
                file=sys.stderr,
            )
            sys.exit(1)

        changed_sections = update_note_sections(target_path, fields)
        cascade_updates = []
        if changed_sections:
            cascade_updates.append(f"Sections updated: {', '.join(changed_sections)}")
        if args.source_note and add_supporting_note(target_path, args.source_note):
            cascade_updates.append(f"Supporting note: [[{args.source_note}]]")
        if cascade_updates and cascade_updates != ["No content changes"] and touch_updated(target_path):
            cascade_updates.append(f"Updated date: {_today_str()}")
        if not cascade_updates:
            cascade_updates.append("No content changes")

        append_operation_log(vault, "cascade", target_path.stem, cascade_updates)
        print(f"[OK] Cascade-updated: {target_path.relative_to(vault)}")
        print("\n[Cascade updates]")
        for item in cascade_updates:
            print(f"  -> {item}")
        return

    if note_type == "conflict-update":
        target_arg = args.target.strip()
        if not target_arg:
            print("Error: --target is required for conflict-update", file=sys.stderr)
            sys.exit(1)
        if not args.source_note.strip():
            print("Error: --source-note is required for conflict-update", file=sys.stderr)
            sys.exit(1)
        claim = (fields.get("claim") or "").strip()
        if not claim:
            print("Error: conflict-update requires fields.claim", file=sys.stderr)
            sys.exit(1)
        conflicts_with = args.conflicts_with.strip()
        if not conflicts_with:
            print("Error: --conflicts-with is required for conflict-update", file=sys.stderr)
            sys.exit(1)

        target_path = Path(target_arg)
        if not target_path.is_absolute():
            target_path = vault / target_path
        if not target_path.exists():
            print(f"Error: target note not found: {target_path}", file=sys.stderr)
            sys.exit(1)

        changed = add_conflict_annotation(
            target_path,
            args.source_note.strip(),
            claim,
            conflicts_with,
            args.status_label.strip() or "unresolved",
        )
        if changed:
            touch_updated(target_path)
        details = [
            f"Conflict source: [[{args.source_note.strip()}]]",
            f"Conflicts with: {conflicts_with}",
            f"Status: {args.status_label.strip() or 'unresolved'}",
        ]
        if changed:
            details.insert(0, "Conflict added")
            details.append(f"Updated date: {_today_str()}")
        else:
            details.insert(0, "Conflict already present")
        append_operation_log(vault, "conflict", target_path.stem, details)
        print(f"[OK] Conflict-updated: {target_path.relative_to(vault)}")
        print("\n[Conflict updates]")
        for item in details:
            print(f"  -> {item}")
        return

    if note_type == "ingest-sync":
        target_arg = args.target.strip()
        if not target_arg:
            print("Error: --target is required for ingest-sync", file=sys.stderr)
            sys.exit(1)
        target_path = _resolve_vault_path(vault, target_arg)
        try:
            summary = run_ingest_sync(vault, target_path, fields)
        except (FileNotFoundError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"[OK] Ingest sync applied: {target_path.relative_to(vault)}")
        if summary["primary_updates"]:
            print("\n[Primary updates]")
            for item in summary["primary_updates"]:
                print(f"  -> {item}")
        if summary["cascade_updates"]:
            print("\n[Cascade updates]")
            for cascade in summary["cascade_updates"]:
                print(f"  -> {cascade['target']}")
                for item in cascade["details"]:
                    print(f"     {item}")
        if summary["conflicts"]:
            print("\n[Conflict updates]")
            for conflict in summary["conflicts"]:
                print(f"  -> {conflict['target']}")
                for item in conflict["details"]:
                    print(f"     {item}")
        return

    if note_type == "suggestion-feedback":
        suggestion_type = args.suggestion_type.strip().lower()
        action = args.feedback_action.strip().lower()
        source_note = args.source_note.strip()
        if not suggestion_type:
            print("Error: --suggestion-type is required for suggestion-feedback", file=sys.stderr)
            sys.exit(1)
        if suggestion_type not in {"link", "merge", "cascade", "topic"}:
            print("Error: --suggestion-type must be one of: link, merge, cascade, topic", file=sys.stderr)
            sys.exit(1)
        if action not in {"reject", "modify-accept"}:
            print("Error: --feedback-action must be one of: reject, modify-accept", file=sys.stderr)
            sys.exit(1)
        if not source_note:
            print("Error: --source-note is required for suggestion-feedback", file=sys.stderr)
            sys.exit(1)

        target_notes = [item.strip() for item in args.targets.split(",") if item.strip()]
        if not target_notes and isinstance(fields.get("target_notes"), list):
            target_notes = [str(item).strip() for item in fields["target_notes"] if str(item).strip()]
        normalized_target_notes = []
        for target in target_notes:
            normalized = _normalize_feedback_target(target)
            if normalized:
                normalized_target_notes.append(normalized)
        reason = args.reason.strip() or str(fields.get("reason", "")).strip()

        events_path = append_suggestion_feedback(
            vault,
            suggestion_type=suggestion_type,
            action=action,
            source_note=source_note,
            target_notes=target_notes,
            reason=reason,
        )
        print(f"[OK] Suggestion feedback recorded: {events_path.relative_to(vault)}")
        print(f"  Type   : {suggestion_type}")
        print(f"  Action : {action}")
        print(f"  Source : {source_note}")
        if normalized_target_notes:
            print(f"  Targets: {', '.join(normalized_target_notes)}")
        if reason:
            print(f"  Reason : {reason}")
        return

    if note_type == "capture":
        capture_url = args.url.strip() or args.title.strip() or str(fields.get("url", "")).strip()
        if not capture_url:
            print("Error: --url is required for capture", file=sys.stderr)
            sys.exit(1)
        if capture_fetch_url is None:
            print("Error: capture importers are unavailable", file=sys.stderr)
            sys.exit(1)

        try:
            import_result = capture_fetch_url(capture_url)
        except Exception as e:
            print(f"Error: failed to capture URL: {e}", file=sys.stderr)
            sys.exit(1)

        title, capture_fields = _capture_fields_from_import_result(import_result, fields)
        if not title:
            fallback = capture_url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
            title = fallback or "Captured Content"

        if args.dry_run:
            print("[Capture preview]")
            print(json.dumps(
                {
                    "title": title,
                    "platform": import_result.platform,
                    "source_url": import_result.source_url,
                    "summary": import_result.summary,
                    "metadata": import_result.metadata or {},
                },
                ensure_ascii=False,
                indent=2,
            ))
            print("\n[Fields]")
            print(json.dumps(capture_fields, ensure_ascii=False, indent=2))
            return

        filepath = write_note(
            vault=vault,
            note_type="literature",
            title=title,
            fields=capture_fields,
            is_draft=args.draft == "true",
        )
        rel_path = filepath.relative_to(vault)
        print(f"[OK] Captured: {rel_path}")
        print(f"  Platform: {import_result.platform}")
        print(f"  Source  : {import_result.source_url}")
        if import_result.summary:
            print(f"  Summary : {import_result.summary[:120]}")
        return

    # --- Fleeting: special case ---
    if note_type == "fleeting":
        content = fields.get("content", "").strip()
        if not content:
            print("Error: fleeting note requires fields.content", file=sys.stderr)
            sys.exit(1)
        tags = fields.get("tags", "").strip()
        if args.dry_run:
            now = datetime.now().strftime("%H:%M")
            tag_part = f" {tags}" if tags else ""
            today = date.today().strftime("%Y-%m-%d")
            print(f"[DRY RUN] Would append to: 01-DailyNotes/{today}.md\n")
            print(f"- {now} {content}{tag_part}")
            return
        filepath = append_fleeting(vault, content, tags)
        rel = filepath.relative_to(vault)
        print(f"[OK] Appended to: {rel}")
        return

    # --- Standard note types ---
    is_draft = args.draft == "true"
    title = args.title.strip()
    if not title:
        print("Error: --title is required for this note type", file=sys.stderr)
        sys.exit(1)

    if note_type == "article" and not args.dry_run:
        duplicate = _check_duplicate(vault, note_type, title)
        if duplicate is not None:
            print(f"[OK] Reused existing: {duplicate.relative_to(vault)}")
            return

    if args.dry_run:
        content = RENDERERS[note_type](title, fields, is_draft)
        if note_type == "article":
            duplicate = _check_duplicate(vault, note_type, title)
            if duplicate is not None:
                print("[INGEST PREVIEW]")
                SEP = "=" * 52
                print(SEP)
                print("Action  : reuse existing")
                print(f"Target  : {duplicate.relative_to(vault)}")
                print(SEP)
                print(content)
                print(SEP)
                return
        action, existing_path, planned_path = _classify_ingest_action(
            vault, note_type, title, is_draft
        )
        SEP = "─" * 52
        print("[INGEST PREVIEW]")
        print(SEP)
        print(f"Action  : {action}")
        print(f"Target  : {planned_path.relative_to(vault)}")
        if existing_path:
            print(f"Existing: {existing_path.relative_to(vault)}")
            print(f"Diff    : {_section_diff_summary(existing_path, content)}")
            print(f"Note    : existing note unchanged — use --type merge-update to update in place")
        print(SEP)
        print(content)
        print(SEP)
        suggestions = suggest_links(vault, planned_path)
        if suggestions:
            print("[Link suggestions]")
            for rel, section in suggestions:
                print(f"  → {rel}  ({section}  ← add [[{planned_path.stem}]])")
            _print_feedback_hint(
                source_note=planned_path.stem,
                suggestion_type="link",
                targets=[str(rel) for rel, _ in suggestions],
                reason="Use if you reject these link suggestions or choose a narrower target.",
            )
        new_topic_hint = suggest_new_topic(planned_path, suggestions)
        if new_topic_hint:
            print(f"\n[Topic suggestion]\n  {new_topic_hint}")
            topic_name = new_topic_hint.removeprefix("Consider creating: ").strip()
            _print_feedback_hint(
                source_note=planned_path.stem,
                suggestion_type="topic",
                targets=[topic_name] if topic_name else [],
                reason="Use if you reject this topic suggestion or create a different topic instead.",
            )
        return

    filepath = write_note(
        vault=vault,
        note_type=note_type,
        title=title,
        fields=fields,
        is_draft=is_draft,
    )

    rel_path = filepath.relative_to(vault)
    print(f"[OK] Written: {rel_path}")

    post_write_updates = []
    if args.source_note and add_supporting_note(filepath, args.source_note):
        post_write_updates.append(f"Supporting note: [[{args.source_note}]]")
    if args.source_ref and add_source_reference(filepath, args.source_ref):
        post_write_updates.append(f"Source added: {args.source_ref}")
    if post_write_updates:
        append_operation_log(vault, "update", filepath.stem, post_write_updates)
        print("\n[Post-write updates]")
        for item in post_write_updates:
            print(f"  -> {item}")

    suggestions = suggest_links(vault, filepath)
    if suggestions:
        print("\n[Link suggestions]")
        for rel, section in suggestions:
            print(f"  → {rel}  ({section}  ← add [[{filepath.stem}]])")
        _print_feedback_hint(
            source_note=filepath.stem,
            suggestion_type="link",
            targets=[str(rel) for rel, _ in suggestions],
            reason="Use if you reject these link suggestions or choose a narrower target.",
        )

    new_topic_hint = suggest_new_topic(filepath, suggestions)
    if new_topic_hint:
        print("\n[Topic suggestion]")
        print(f"  {new_topic_hint}")
        topic_name = new_topic_hint.removeprefix("Consider creating: ").strip()
        _print_feedback_hint(
            source_note=filepath.stem,
            suggestion_type="topic",
            targets=[topic_name] if topic_name else [],
            reason="Use if you reject this topic suggestion or create a different topic instead.",
        )

    # Orphan-on-create: emit correction if no topic parent and note is in Knowledge
    _maybe_emit_orphan_correction(vault, filepath, suggestions, is_draft)


if __name__ == "__main__":
    main()
