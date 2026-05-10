"""
knowledge_service.py — Query, organize, and lint the vault.

Top-level service operations:

  - :func:`query_vault` — session-first, topic-first retrieval; returns
    a structured payload with tier-1 topic summaries and (optionally)
    tier-2 grouped detail notes.
  - :func:`organize_vault` — surface related notes for a query and
    suggest whether to converge into a topic or a MOC.
  - :func:`lint_vault` — scan for quality issues (broken links,
    orphans, inbox backlog, skeletons, stale notes, stale synthesis),
    optionally auto-fix simple frontmatter omissions.

Composes :mod:`frontmatter`, :mod:`linker`, :mod:`log_writer`,
:mod:`session_helpers`, with optional :mod:`profile_manager`.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

try:
    from . import frontmatter as fm
    from .linker import (
        suggest_links,
        suggest_new_topic,
        suggestion_keywords_from_stem,
    )
    from .log_writer import append_correction_events, append_operation_log
    from .session_helpers import (
        find_session_relevant_notes,
        record_session_note,
        record_session_query,
    )
except ImportError:  # script-mode fallback
    import frontmatter as fm  # type: ignore[no-redef]
    from linker import (  # type: ignore[no-redef]
        suggest_links,
        suggest_new_topic,
        suggestion_keywords_from_stem,
    )
    from log_writer import (  # type: ignore[no-redef]
        append_correction_events,
        append_operation_log,
    )
    from session_helpers import (  # type: ignore[no-redef]
        find_session_relevant_notes,
        record_session_note,
        record_session_query,
    )

# Optional profile context — gracefully degrade when missing.
try:
    try:
        from .profile_manager import read_profile  # type: ignore[attr-defined]
    except ImportError:
        from profile_manager import read_profile  # type: ignore[no-redef]
except ImportError:
    read_profile = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Lint thresholds (kept module-level so callers / tests can monkeypatch)
# ---------------------------------------------------------------------------

INBOX_BACKLOG_DAYS = 7
STALE_DAYS = 90
STALE_SYNTHESIS_DAYS = 30
SKELETON_RATIO = 0.5

SKIP_LINT_DIRS = {"01-DailyNotes", "04-Archive", "Templates", "Attachments"}
KNOWLEDGE_DIRS = {"02-Projects", "03-Knowledge"}


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def query_keywords(query_text: str) -> list[str]:
    """Return meaningful query keywords shared across retrieval helpers."""

    keywords = suggestion_keywords_from_stem(query_text)
    if keywords:
        return keywords
    return [part for part in re.split(r"[\s\-_]+", query_text) if len(part) >= 2]


def extract_profile_section(profile_context: str, section_title: str) -> str:
    """Return the body of a ``## Title`` block from concatenated profile text."""

    pattern = rf"(?ms)^## {re.escape(section_title)}\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, profile_context)
    if not match:
        return ""
    return match.group(1).strip()


def profile_query_keywords(profile_context: str) -> list[str]:
    """Lightweight query expansion keywords from profile context."""

    if not profile_context:
        return []

    blocks = []
    for section_title in ("常讨论话题", "编程语言", "工具链", "AI 行为偏好"):
        block = extract_profile_section(profile_context, section_title)
        if block:
            blocks.append(block)

    keywords: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        for kw in suggestion_keywords_from_stem(block):
            cleaned = kw.strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            keywords.append(cleaned)
    return keywords


def topic_summary_payload(note_path: Path, text: str) -> dict:
    """Build the Tier 1 payload for a topic note."""

    return {
        "path": note_path,
        "title": note_path.stem,
        "主题说明": fm.get_section(text, "主题说明"),
        "当前结论": fm.get_section(text, "当前结论"),
        "未解决问题": fm.get_section(text, "未解决问题"),
    }


def _read_profile_context(vault: Path) -> str:
    if read_profile is None:
        return ""
    try:
        return read_profile(vault).strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Query / organize
# ---------------------------------------------------------------------------


def query_vault(
    vault: Path,
    query_text: str,
    include_details: bool = False,
    limit: int = 5,
) -> dict:
    """Query the vault with session-first, topic-first retrieval.

    Returns ``{tier1_topics, tier2_grouped, orphans, profile_context}``.
    """

    record_session_query(vault, query_text)
    profile_context = _read_profile_context(vault)
    keywords = [kw.lower() for kw in query_keywords(query_text)]
    for kw in profile_query_keywords(profile_context):
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
                    fm.get_section(text, "主题说明").lower(),
                    fm.get_section(text, "当前结论").lower(),
                    fm.get_section(text, "未解决问题").lower(),
                ],
            )
        )
        overlap = sum(1 for kw in keywords if kw in haystack)
        if keywords and overlap == 0:
            continue
        topic_payloads.append(
            (100 + overlap * 10, topic_summary_payload(session_path, text))
        )
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
                        fm.get_section(text, "主题说明").lower(),
                        fm.get_section(text, "当前结论").lower(),
                        fm.get_section(text, "未解决问题").lower(),
                    ],
                )
            )
            overlap = sum(1 for kw in keywords if kw in haystack)
            if keywords and overlap == 0:
                continue
            topic_payloads.append(
                (overlap * 10, topic_summary_payload(topic_path, text))
            )

    topic_payloads.sort(key=lambda item: (-item[0], item[1]["title"]))
    tier1_topics = [payload for _, payload in topic_payloads[:limit]]

    if tier1_topics and not include_details:
        for item in tier1_topics:
            record_session_note(vault, "topic", item["path"])
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
            overlap = sum(
                1 for kw in keywords
                if kw in note_path.stem.lower() or kw in haystack
            )
            if keywords and overlap == 0:
                continue

            note_item = {
                "path": note_path,
                "title": note_path.stem,
                "excerpt": (
                    fm.get_section(text, "核心观点")
                    or fm.get_section(text, "方法要点")
                    or fm.get_section(text, "一句话定义")
                    or fm.get_section(text, "项目描述")
                )[:200],
            }
            links = fm.extract_wikilinks(text)
            parent_topics = sorted(
                link for link in links if link.startswith("Topic - ")
            )
            if not parent_topics:
                orphans.append(note_item)
                continue
            matched_parent = next(
                (t for t in parent_topics if t in topic_titles), parent_topics[0]
            )
            grouped.setdefault(matched_parent, []).append(note_item)

    tier2_grouped = [
        {"topic": topic, "notes": notes[:limit]}
        for topic, notes in sorted(grouped.items(), key=lambda item: item[0])
    ]

    for item in tier1_topics:
        record_session_note(vault, "topic", item["path"])
    for group in tier2_grouped:
        for note in group["notes"]:
            record_session_note(vault, "note", note["path"])
    for note in orphans[:limit]:
        record_session_note(vault, "note", note["path"])

    return {
        "tier1_topics": tier1_topics,
        "tier2_grouped": tier2_grouped,
        "orphans": orphans[:limit],
        "profile_context": profile_context,
    }


def organize_vault(vault: Path, query_text: str, limit: int = 10) -> dict:
    """Return a session-first organization view for related notes."""

    record_session_query(vault, query_text)
    profile_context = _read_profile_context(vault)
    keywords = [kw.lower() for kw in query_keywords(query_text)]
    for kw in profile_query_keywords(profile_context):
        lowered = kw.lower()
        if lowered not in keywords:
            keywords.append(lowered)

    session_hits = find_session_relevant_notes(
        vault, query_text, limit=min(limit, 5)
    )
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
            note_type = fm.parse_dict(text).get("type", "")
            parent_topics = sorted(
                link for link in fm.extract_wikilinks(text)
                if link.startswith("Topic - ")
            )
            note_item = {
                "path": note_path,
                "title": note_path.stem,
                "relative_path": str(rel),
                "type": note_type,
                "excerpt": (
                    fm.get_section(text, "当前结论")
                    or fm.get_section(text, "核心观点")
                    or fm.get_section(text, "一句话定义")
                    or fm.get_section(text, "项目描述")
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
        1 for item in selected
        if item["type"] in {"literature", "concept", "project"}
    )
    orphan_match_count = sum(
        1 for item in selected
        if item["type"] in {"literature", "concept", "project"}
        and not item["parent_topics"]
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
        reasons.append(
            f"{orphan_match_count} orphan source note(s) suggest fragmentation"
        )
    elif orphan_match_count == 1:
        topic_score += 1
        reasons.append("1 orphan source note may need a clearer topic home")
    if session_match_count:
        topic_score += 2
        reasons.append(
            f"{session_match_count} match(es) are active in the current session"
        )
    if inbox_match_count:
        topic_score += 1
        reasons.append(
            f"{inbox_match_count} inbox note(s) are waiting to be organized"
        )
    if source_match_count >= 2:
        topic_score += 1
        reasons.append(
            f"{source_match_count} source note(s) share the current subject"
        )

    if topic_match_count == 0 and len(selected) <= 1:
        moc_score += 3
        reasons.append("only a shallow cluster was found")
    if (
        topic_match_count == 0
        and orphan_match_count == 0
        and source_match_count <= 1
    ):
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
        record_session_note(
            vault,
            "topic" if item["type"] == "topic" else "note",
            item["path"],
        )

    return {
        "session_hits": session_hits,
        "matches": selected,
        "suggested_output": suggestion,
        "confidence": confidence,
        "reasons": reasons,
        "new_topic_hint": new_topic_hint,
        "profile_context": profile_context,
    }


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------


def fix_frontmatter(text: str, path: Path, fmd: dict) -> tuple[str, list[str]]:
    """Add missing required frontmatter fields. Returns ``(new_text, fixes)``."""

    today = date.today().strftime("%Y-%m-%d")
    defaults = {
        "status": "active",
        "created": today,
        "updated": today,
        "reviewed": "false",
    }
    missing = {k: v for k, v in defaults.items() if k not in fmd}
    if not missing:
        return text, []

    end = text.find("---", 3)
    if end == -1:
        return text, [
            f"{path.name}: skipped auto-fix (malformed frontmatter, no closing ---)"
        ]
    insert_lines = "".join(f"{k}: {v}\n" for k, v in missing.items())
    new_text = text[:end] + insert_lines + text[end:]
    fixes = [
        f"{path.name}: added missing frontmatter field(s): {', '.join(missing)}"
    ]
    return new_text, fixes


def lint_vault(vault: Path, auto_fix: bool = False) -> None:
    """Scan vault for quality issues, optionally auto-fix simple ones."""

    all_notes = list(vault.rglob("*.md"))
    note_stems = {f.stem for f in all_notes}

    contents: dict[Path, str] = {}
    for f in all_notes:
        try:
            contents[f] = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            contents[f] = ""

    today = date.today()
    auto_fixes: list[str] = []
    broken: list[str] = []
    orphans: list[str] = []
    inbox_backlog: list[str] = []
    stale_synthesis: list[str] = []
    skeletons: list[str] = []
    stale: list[str] = []
    correction_events: list[dict] = []

    referenced: set[str] = set()
    for text in contents.values():
        for link in fm.extract_wikilinks(text):
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
        fmd = fm.parse_dict(text)

        if auto_fix and text.startswith("---"):
            new_text, fixes = fix_frontmatter(text, note_path, fmd)
            if fixes:
                note_path.write_text(new_text, encoding="utf-8")
                contents[note_path] = new_text
                text = new_text
                fmd = fm.parse_dict(new_text)
                auto_fixes.extend(fixes)

        if text.startswith("---"):
            missing_frontmatter = [
                key for key in ("status", "created", "updated", "reviewed")
                if key not in fmd
            ]
            if missing_frontmatter:
                add_correction(
                    note_path,
                    "missing-frontmatter",
                    f"missing field(s): {', '.join(missing_frontmatter)}",
                )

        broken_here = [
            lnk for lnk in fm.extract_wikilinks(text)
            if lnk and lnk not in note_stems
        ]
        for lnk in broken_here:
            broken.append(f"  {rel} → [[{lnk}]]")
            add_correction(note_path, "broken-link", f"[[{lnk}]]")

        if top_dir in SKIP_LINT_DIRS:
            continue

        if top_dir in KNOWLEDGE_DIRS and note_path.stem not in referenced:
            orphans.append(f"  {rel}")
            add_correction(note_path, "orphan", "not referenced from any note")

        if top_dir == "00-Inbox":
            created_str = fmd.get("created", "")
            if created_str:
                try:
                    age = (today - date.fromisoformat(created_str)).days
                    if age > INBOX_BACKLOG_DAYS:
                        inbox_backlog.append(f"  {rel} ({age} days old)")
                        add_correction(
                            note_path, "inbox-backlog", f"{age} days old"
                        )
                except ValueError:
                    pass

        sections = re.split(r"^#+\s.*$", text, flags=re.MULTILINE)
        section_count = len(sections) - 1
        empty_count = sum(1 for s in sections[1:] if not s.strip())
        if section_count > 0 and empty_count / section_count > SKELETON_RATIO:
            skeletons.append(
                f"  {rel} ({empty_count}/{section_count} sections empty)"
            )
            add_correction(
                note_path,
                "skeleton",
                f"{empty_count}/{section_count} sections empty",
            )

        if fmd.get("status") == "active":
            updated_str = fmd.get("updated", "")
            if updated_str:
                try:
                    age = (today - date.fromisoformat(updated_str)).days
                    if age > STALE_DAYS:
                        stale.append(f"  {rel} ({age} days since update)")
                        add_correction(
                            note_path, "stale", f"{age} days since update"
                        )
                except ValueError:
                    pass

    topic_dir = vault / "03-Knowledge" / "Topics"
    if topic_dir.exists():
        for topic_path, topic_text in contents.items():
            if topic_path.parent != topic_dir:
                continue
            topic_fm = fm.parse_dict(topic_text)
            topic_updated_str = topic_fm.get("updated", "")
            if not topic_updated_str:
                continue
            try:
                topic_updated = date.fromisoformat(topic_updated_str)
            except ValueError:
                continue

            linked_stems = fm.extract_wikilinks(topic_text)
            lagging: list[str] = []
            for stem in linked_stems:
                linked_file = next(
                    (f for f in all_notes if f.stem == stem), None
                )
                if linked_file is None:
                    continue
                linked_fm = fm.parse_dict(contents.get(linked_file, ""))
                linked_updated_str = linked_fm.get("updated", "")
                if not linked_updated_str:
                    continue
                try:
                    linked_updated = date.fromisoformat(linked_updated_str)
                except ValueError:
                    continue
                lag = (linked_updated - topic_updated).days
                if lag > STALE_SYNTHESIS_DAYS:
                    lagging.append(f"{stem} (+{lag}d)")

            if lagging:
                rel = topic_path.relative_to(vault)
                detail = (
                    f"linked notes updated after topic: {', '.join(lagging[:3])}"
                )
                stale_synthesis.append(f"  {rel} — {detail}")
                add_correction(topic_path, "stale-synthesis", detail)

    total = len(all_notes)
    print(f"[Lint] Scanned {total} note(s) in {vault}\n")

    if auto_fixes:
        print(f"[Auto-fixed] ({len(auto_fixes)})")
        for f in auto_fixes:
            print(f"  ✓ {f}")
        print()

    sections_report = [
        ("[Broken links]", broken),
        ("[Orphan notes] (not referenced from any MOC/Topic)", orphans),
        ("[Inbox backlog] (stuck >7 days)", inbox_backlog),
        ("[Skeleton notes] (>50% fields empty)", skeletons),
        ("[Stale notes] (not updated in 90+ days)", stale),
        (
            f"[Stale synthesis] (topic synthesis lags linked notes by >{STALE_SYNTHESIS_DAYS}d)",
            stale_synthesis,
        ),
    ]
    found_issues = False
    for header, items in sections_report:
        if items:
            found_issues = True
            print(f"{header} ({len(items)})")
            for item in items:
                print(f"⚠{item}")
            print()

    if not found_issues and not auto_fixes:
        print("✓ No issues found.")

    corrections_path = append_correction_events(vault, correction_events)

    issue_count = sum(len(items) for _, items in sections_report)
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
