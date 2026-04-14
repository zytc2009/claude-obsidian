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
from datetime import date, datetime, timedelta
from pathlib import Path

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
}

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
    status = "draft" if is_draft else "active"
    return (
        f"---\n"
        f"type: {note_type}\n"
        f"status: {status}\n"
        f"topic: []\n"
        f"tags: []\n"
        f"source: {source}\n"
        f"author: {author}\n"
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
    target_dir = get_target_path(vault, note_type, is_draft)
    target_dir.mkdir(parents=True, exist_ok=True)

    prefix = NOTE_CONFIG[note_type]["prefix"]
    filename = make_filename(prefix, title, target_dir)
    filepath = target_dir / filename

    content = RENDERERS[note_type](title, fields, is_draft)
    filepath.write_text(content, encoding="utf-8")

    # Incrementally update _index.md (skip drafts — they live in Inbox)
    if not is_draft:
        section_map = {
            "literature": "Literature",
            "concept": "Concepts",
            "topic": "Topics",
            "project": "Projects",
            "moc": "MOCs",
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

    return filepath


# ---------------------------------------------------------------------------
# Vault init
# ---------------------------------------------------------------------------

VAULT_DIRS = [
    ("00-Inbox", None),
    ("01-DailyNotes", None),
    ("02-Projects", None),
    ("03-Knowledge", ["Concepts", "Literature", "MOCs", "Topics"]),
    ("04-Archive", None),
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
                    target_name = str(target).strip()
                    if not target_name:
                        continue
                    target_adjustments = adjustments.setdefault(
                        target_name, {"reject": 0, "modify-accept": 0}
                    )
                    target_adjustments[action] += 1
    except OSError:
        return {}
    return adjustments


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
]

_SUPPORTING_SECTION_TITLE = "# Supporting notes"
_SOURCES_SECTION_TITLE = "# Sources"
_CONFLICTS_SECTION_TITLE = "# Conflicts"
_TOPIC_CASCADE_FIELDS = {"主题说明", "核心问题", "重要资料", "相关项目", "当前结论", "未解决问题"}


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
    event = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "event_type": "suggestion_feedback",
        "suggestion_type": suggestion_type,
        "source_note": source_note,
        "target_notes": target_notes,
        "action": action,
        "reason": reason,
    }
    events_path = vault / _EVENTS_FILE
    append_jsonl_events(events_path, [event])

    details = [
        f"Suggestion type: {suggestion_type}",
        f"Action: {action}",
        f"Targets: {', '.join(target_notes) if target_notes else '(none)'}",
    ]
    if reason:
        details.append(f"Reason: {reason}")
    append_operation_log(vault, "suggestion-feedback", source_note, details)
    return events_path


def _print_feedback_hint(
    source_note: str, suggestion_type: str, targets: list[str], reason: str = ""
) -> None:
    """Print a copyable feedback command hint for suggestion-producing flows."""
    if not source_note or not suggestion_type:
        return

    joined_targets = ",".join(targets)
    print("\n[Feedback hint]")
    print("  Record a rejection or modified acceptance with:")
    print(
        "  python skills/obsidian/obsidian_writer.py "
        f"--type suggestion-feedback --source-note \"{source_note}\" "
        f"--suggestion-type {suggestion_type} --feedback-action reject "
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
    """Return all wikilink targets from text, stripping heading anchors."""
    pattern = r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]"
    return {m.group(1).strip() for m in re.finditer(pattern, text)}


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
    insert_lines = "".join(f"{k}: {v}\n" for k, v in missing.items())
    new_text = text[:end] + insert_lines + text[end:]
    fixes = [f"{path.name}: added missing frontmatter field(s): {', '.join(missing)}"]
    return new_text, fixes


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

_INBOX_BACKLOG_DAYS = 7
_STALE_DAYS = 90
_SKELETON_RATIO = 0.5   # fraction of _待补充_ sections that triggers "skeleton"

_SKIP_LINT_DIRS = {"01-DailyNotes", "04-Archive"}
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

        # --- Auto-fix: missing frontmatter fields ---
        if auto_fix and text.startswith("---"):
            new_text, fixes = _fix_frontmatter(text, note_path, fm)
            if fixes:
                note_path.write_text(new_text, encoding="utf-8")
                contents[note_path] = new_text
                auto_fixes.extend(fixes)

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
        choices=list(NOTE_CONFIG.keys()) + ["fleeting", "init", "lint", "index", "merge-candidates", "merge-update", "cascade-candidates", "cascade-update", "conflict-update", "ingest-sync", "suggestion-feedback"],
        help="Note type",
    )
    parser.add_argument(
        "--auto-fix",
        action="store_true",
        help="Auto-fix simple issues (missing frontmatter fields) during lint",
    )
    parser.add_argument("--title", default="", help="Note title")
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

    # --- Index: special case ---
    if note_type == "index":
        index_path = rebuild_index(vault)
        print(f"[OK] Index rebuilt: {index_path.relative_to(vault)}")
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
        if target_notes:
            print(f"  Targets: {', '.join(target_notes)}")
        if reason:
            print(f"  Reason : {reason}")
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

    if args.dry_run:
        content = RENDERERS[note_type](title, fields, is_draft)
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


if __name__ == "__main__":
    main()
