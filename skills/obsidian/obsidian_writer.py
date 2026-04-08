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

VAULT_PATH = Path(os.environ.get("OBSIDIAN_VAULT_PATH", "D:/obsidian"))

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
        "required": ["主题说明", "核心概念"],
    },
    "project": {
        "prefix": "Project",
        "target": "02-Projects",
        "required": ["项目目标", "完成标准", "任务拆分"],
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
    """Return field value or placeholder if empty."""
    return fields.get(key, "").strip() or "_待补充_"


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

# 我想回答的问题
{_f(fields, "问题列表")}

# 核心概念
{_f(fields, "核心概念")}

# 重要资料
{_f(fields, "重要资料")}

# 当前结论
{_f(fields, "当前结论")}

# 未解决问题
{_f(fields, "未解决问题")}

# 下一步学习路线
{_f(fields, "下一步路线")}
"""


def render_project(title: str, fields: dict, is_draft: bool = False) -> str:
    fm = _frontmatter("project", fields, is_draft)
    return f"""{fm}

# {title}

# 项目目标
{_f(fields, "项目目标")}

# 完成标准
{_f(fields, "完成标准")}

# 当前状态
{fields.get("当前状态", "进行中")}

# 任务拆分
{_f(fields, "任务拆分")}

# 相关资料
{_f(fields, "相关资料")}

# 风险与阻塞
{_f(fields, "风险与阻塞")}

# 实验记录
{_f(fields, "实验记录")}

# 产出
{_f(fields, "产出")}
"""


def render_moc(title: str, fields: dict, is_draft: bool = False) -> str:
    fm = _frontmatter("moc", fields, is_draft)
    links = fields.get("links", "").strip()
    return f"""{fm}

# {title}

# 主题地图

# 概念
{links if links else "_待补充_"}

# 资料
_待补充_

# 项目
_待补充_

# 常见问题
_待补充_

# 输出内容
_待补充_
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

def suggest_links(vault: Path, new_note_path: Path) -> list:
    """Return MOC/Topic files that likely should link to the new note.

    Heuristic: search MOCs and Topics for any word from the new note's stem
    that is ≥ 4 characters, to avoid spurious matches on short tokens.
    Returns a list of (relative_path, section_hint) tuples.
    """
    stem = new_note_path.stem  # e.g. "Literature - Attention Is All You Need"
    # Extract meaningful words (≥4 chars, not common stop words)
    _STOP = {"with", "from", "that", "this", "into", "over", "under",
              "about", "have", "been", "were", "will", "does", "their"}
    words = [
        w for w in re.split(r"[\s\-_]+", stem)
        if len(w) >= 4 and w.lower() not in _STOP and not w.startswith(("Literature", "Concept", "Topic", "Project", "MOC"))
    ]
    if not words:
        return []

    candidates = []
    for search_dir in ["03-Knowledge/MOCs", "03-Knowledge/Topics"]:
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
            # Already links to the new note?
            if new_note_path.stem in text:
                continue
            # Any keyword match?
            lower_text = text.lower()
            if any(w.lower() in lower_text for w in words):
                fm_type = _parse_frontmatter(text).get("type", "")
                section = "# 资料" if fm_type == "moc" else "# 重要资料"
                candidates.append((md_file.relative_to(vault), section))

    return candidates


# ---------------------------------------------------------------------------
# Index maintenance
# ---------------------------------------------------------------------------

_INDEX_FILE = "_index.md"

_INDEX_DIRS = [
    ("02-Projects", "Projects"),
    ("03-Knowledge/Topics", "Topics"),
    ("03-Knowledge/MOCs", "MOCs"),
    ("03-Knowledge/Concepts", "Concepts"),
    ("03-Knowledge/Literature", "Literature"),
]


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

    # Build set of all referenced note stems across all files
    referenced: set = set()
    for text in contents.values():
        for link in _extract_wikilinks(text):
            referenced.add(link)

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
                auto_fixes.extend(fixes)

        # --- Broken wikilinks ---
        broken_here = [
            lnk for lnk in _extract_wikilinks(text)
            if lnk and lnk not in note_stems
        ]
        for lnk in broken_here:
            broken.append(f"  {rel} → [[{lnk}]]")

        if top_dir in _SKIP_LINT_DIRS:
            continue

        # --- Orphan notes (Knowledge + Projects, not referenced anywhere) ---
        if top_dir in _KNOWLEDGE_DIRS and note_path.stem not in referenced:
            orphans.append(f"  {rel}")

        # --- Inbox backlog ---
        if top_dir == "00-Inbox":
            created_str = fm.get("created", "")
            if created_str:
                try:
                    age = (today - date.fromisoformat(created_str)).days
                    if age > _INBOX_BACKLOG_DAYS:
                        inbox_backlog.append(f"  {rel} ({age} days old)")
                except ValueError:
                    pass

        # --- Skeleton notes ---
        placeholder_count = text.count("_待补充_")
        section_count = len(re.findall(r"^#+\s", text, re.MULTILINE))
        if section_count > 0 and placeholder_count / section_count > _SKELETON_RATIO:
            skeletons.append(
                f"  {rel} ({placeholder_count}/{section_count} sections empty)"
            )

        # --- Stale notes (active, not updated in 90+ days) ---
        if fm.get("status") == "active":
            updated_str = fm.get("updated", "")
            if updated_str:
                try:
                    age = (today - date.fromisoformat(updated_str)).days
                    if age > _STALE_DAYS:
                        stale.append(f"  {rel} ({age} days since update)")
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
        choices=list(NOTE_CONFIG.keys()) + ["fleeting", "init", "lint", "index"],
        help="Note type",
    )
    parser.add_argument(
        "--auto-fix",
        action="store_true",
        help="Auto-fix simple issues (missing frontmatter fields) during lint",
    )
    parser.add_argument("--title", default="", help="Note title")
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
        target_dir = get_target_path(vault, note_type, is_draft)
        prefix = NOTE_CONFIG[note_type]["prefix"]
        filename = make_filename(prefix, title, target_dir)
        print(f"[DRY RUN] Would write to: {target_dir / filename}\n")
        print(content)
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

    suggestions = suggest_links(vault, filepath)
    if suggestions:
        print("\n[Link suggestions]")
        for rel, section in suggestions:
            print(f"  → {rel}  ({section}  ← add [[{filepath.stem}]])")


if __name__ == "__main__":
    main()
