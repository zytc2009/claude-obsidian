"""
index.py — Build and maintain the vault's ``_index.md`` navigation page.

The index is rebuilt from scratch by scanning a fixed set of managed
directories (``02-Projects``, ``03-Knowledge/*``, ``06-Articles``).
Each note becomes one bullet line carrying a wikilink, a one-line
summary harvested from frontmatter, and the ``updated`` date. A
"Recent" trailer surfaces notes touched in the last 7 days.

Behavior parity with the original ``obsidian_writer`` implementation:
the line format, section ordering, and recent-window threshold are
preserved exactly so downstream tools and screenshots stay valid.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

try:
    from . import frontmatter as fm
except ImportError:  # script-mode fallback
    import frontmatter as fm  # type: ignore[no-redef]

INDEX_FILE = "_index.md"

INDEX_DIRS: list[tuple[str, str]] = [
    ("02-Projects", "Projects"),
    ("03-Knowledge/Topics", "Topics"),
    ("03-Knowledge/MOCs", "MOCs"),
    ("03-Knowledge/Concepts", "Concepts"),
    ("03-Knowledge/Literature", "Literature"),
    ("06-Articles", "Articles"),
]


def index_entry(note_path: Path) -> str:
    """Return a single index bullet line for ``note_path``."""

    text = note_path.read_text(encoding="utf-8", errors="replace")
    fmd = fm.parse_dict(text)
    summary = (
        fmd.get("主题说明") or fmd.get("一句话定义") or fmd.get("解决的问题") or ""
    ).strip()
    updated = fmd.get("updated", "")
    parts = [f"- [[{note_path.stem}]]"]
    if summary:
        parts.append(f" — {summary[:60]}")
    if updated:
        parts.append(f" ({updated})")
    return "".join(parts)


def rebuild_index(vault: Path) -> Path:
    """Rebuild ``<vault>/_index.md`` from scratch."""

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

    for rel_dir, section_name in INDEX_DIRS:
        target = vault / rel_dir
        if not target.exists():
            continue
        notes = sorted(target.glob("*.md"))
        if not notes:
            continue
        lines.append(f"## {section_name} ({len(notes)})")
        for note in notes:
            lines.append(index_entry(note))
        lines.append("")

    recent_threshold = date.today() - timedelta(days=7)
    recent: list[tuple[str, str]] = []
    for rel_dir, _ in INDEX_DIRS:
        target = vault / rel_dir
        if not target.exists():
            continue
        for note in target.glob("*.md"):
            fmd = fm.parse_dict(note.read_text(encoding="utf-8", errors="replace"))
            updated_str = fmd.get("updated", "")
            if not updated_str:
                continue
            try:
                if date.fromisoformat(updated_str) >= recent_threshold:
                    recent.append((updated_str, note.stem))
            except ValueError:
                continue

    if recent:
        recent.sort(reverse=True)
        lines.append("## Recent (last 7 days)")
        for updated, stem in recent[:10]:
            lines.append(f"- {updated}: [[{stem}]]")
        lines.append("")

    index_path = vault / INDEX_FILE
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def append_to_index(vault: Path, note_path: Path, section_name: str) -> None:
    """Incrementally insert ``note_path`` under ``## section_name``.

    Falls back to a full rebuild if the index is missing or doesn't
    yet contain the requested section.
    """

    index_path = vault / INDEX_FILE
    if not index_path.exists():
        rebuild_index(vault)
        return

    text = index_path.read_text(encoding="utf-8")
    if note_path.stem in text:
        return  # already listed

    entry = index_entry(note_path)
    header = f"## {section_name}"
    if header not in text:
        rebuild_index(vault)
        return

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
