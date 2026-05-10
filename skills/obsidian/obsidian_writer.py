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
    from .image_cache import cache_images as _cache_images
except ImportError:
    try:
        from image_cache import cache_images as _cache_images
    except ImportError:  # pragma: no cover - optional integration fallback
        _cache_images = None  # type: ignore[assignment]

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

# Note rendering and per-type config moved to templates.py.
try:
    from .templates import (  # noqa: E402
        DAILY_FRONTMATTER,
        NOTE_CONFIG,
        get_target_path,
        is_draft_by_content,
        make_filename,
        render_article,
        render_concept,
        render_literature,
        render_moc,
        render_project,
        render_topic,
    )
    from .templates import _f  # noqa: E402,F401  -- internal callers
    from .templates import render_frontmatter as _frontmatter  # noqa: E402
except ImportError:  # script-mode fallback
    from templates import (  # type: ignore[no-redef]  # noqa: E402
        DAILY_FRONTMATTER,
        NOTE_CONFIG,
        get_target_path,
        is_draft_by_content,
        make_filename,
        render_article,
        render_concept,
        render_literature,
        render_moc,
        render_project,
        render_topic,
    )
    from templates import _f  # type: ignore[no-redef]  # noqa: E402,F401
    from templates import render_frontmatter as _frontmatter  # type: ignore[no-redef]  # noqa: E402


# Session-memory helpers moved to session_helpers.py; re-exported
# here under the underscore-prefixed names used by tests and internal
# callers.
try:
    from .session_helpers import (  # noqa: E402
        find_session_relevant_notes,
        record_session_note as _record_session_note,
        record_session_query,
        resolve_session_note_refs as _resolve_session_note_refs,
        safe_session_memory as _safe_session_memory,
        session_rejected_targets as _session_rejected_targets,
    )
except ImportError:  # script-mode fallback
    from session_helpers import (  # type: ignore[no-redef]  # noqa: E402
        find_session_relevant_notes,
        record_session_note as _record_session_note,
        record_session_query,
        resolve_session_note_refs as _resolve_session_note_refs,
        safe_session_memory as _safe_session_memory,
        session_rejected_targets as _session_rejected_targets,
    )

# Routing utilities, template renderers, and DAILY_FRONTMATTER are
# now imported from templates.py at the top of this file.
#
# (Original implementations removed — see skills/obsidian/templates.py.)


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

# Link / topic suggestion logic moved to linker.py; re-exported here
# under the underscore-prefixed names used by tests and internal
# callers.
try:
    from .linker import (
        cluster_notes as _cluster_notes,
        jaccard as _jaccard,
        load_feedback_adjustments as _load_feedback_adjustments,
        normalize_token as _normalize_token,
        scout_keywords as _scout_keywords,
        scout_topics,
        session_rejected_targets as _session_rejected_targets,
        split_mixed_tokens as _split_mixed_tokens,
        stem_jaccard as _stem_jaccard,
        suggest_cluster_name as _suggest_cluster_name,
        suggest_links,
        suggest_new_topic,
        suggestion_keywords_from_stem as _suggestion_keywords_from_stem,
        topic_candidate_from_stem as _topic_candidate_from_stem,
    )
except ImportError:  # script-mode fallback
    from linker import (  # type: ignore[no-redef]
        cluster_notes as _cluster_notes,
        jaccard as _jaccard,
        load_feedback_adjustments as _load_feedback_adjustments,
        normalize_token as _normalize_token,
        scout_keywords as _scout_keywords,
        scout_topics,
        session_rejected_targets as _session_rejected_targets,
        split_mixed_tokens as _split_mixed_tokens,
        stem_jaccard as _stem_jaccard,
        suggest_cluster_name as _suggest_cluster_name,
        suggest_links,
        suggest_new_topic,
        suggestion_keywords_from_stem as _suggestion_keywords_from_stem,
        topic_candidate_from_stem as _topic_candidate_from_stem,
    )


def _normalize_feedback_target(target: str) -> str:
    """Normalize feedback targets to note stems so hints and scoring share one key."""
    target_name = str(target).strip()
    if not target_name:
        return ""
    target_path = Path(target_name)
    return target_path.stem.strip() or target_name


# ---------------------------------------------------------------------------
# Ingest preview helpers
# ---------------------------------------------------------------------------


# Ingest classification, candidate finders, and run_ingest_sync moved
# to ingest_service.py; re-exported here under the underscore-prefixed
# names used by tests and internal callers.
try:
    from .ingest_service import (
        TOPIC_CASCADE_FIELDS as _TOPIC_CASCADE_FIELDS,
        check_duplicate as _check_duplicate,
        classify_ingest_action as _classify_ingest_action,
        find_cascade_candidates,
        find_merge_candidates,
        normalize_title as _normalize_title,
        resolve_vault_path as _resolve_vault_path,
        run_ingest_sync,
        section_diff_summary as _section_diff_summary,
    )
except ImportError:  # script-mode fallback
    from ingest_service import (  # type: ignore[no-redef]
        TOPIC_CASCADE_FIELDS as _TOPIC_CASCADE_FIELDS,
        check_duplicate as _check_duplicate,
        classify_ingest_action as _classify_ingest_action,
        find_cascade_candidates,
        find_merge_candidates,
        normalize_title as _normalize_title,
        resolve_vault_path as _resolve_vault_path,
        run_ingest_sync,
        section_diff_summary as _section_diff_summary,
    )



# ---------------------------------------------------------------------------
# Index maintenance
# ---------------------------------------------------------------------------

_INDEX_FILE = "_index.md"

# Log/event-stream constants moved to log_writer.py; re-exported here
# under the underscore-prefixed names used by tests and legacy callers.
try:
    from .log_writer import (
        CORRECTIONS_FILE as _CORRECTIONS_FILE,
        EVENTS_FILE as _EVENTS_FILE,
        LOG_ARCHIVE_FILE as _LOG_ARCHIVE_FILE,
        LOG_FILE as _LOG_FILE,
        MAX_LOG_ENTRIES as _MAX_LOG_ENTRIES,
    )
except ImportError:  # script-mode fallback
    from log_writer import (  # type: ignore[no-redef]
        CORRECTIONS_FILE as _CORRECTIONS_FILE,
        EVENTS_FILE as _EVENTS_FILE,
        LOG_ARCHIVE_FILE as _LOG_ARCHIVE_FILE,
        LOG_FILE as _LOG_FILE,
        MAX_LOG_ENTRIES as _MAX_LOG_ENTRIES,
    )

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


# Index helpers now live in skills.obsidian.index. Internal usages
# below import via the alias ``_index_module`` to avoid shadowing the
# original ``_index_entry`` function name in places that still expect
# the (note_path, vault) signature.
try:
    from . import index as _index_module  # noqa: E402
except ImportError:
    import index as _index_module  # type: ignore[no-redef]  # noqa: E402


def _index_entry(note_path: Path, vault: Path) -> str:
    """Backward-compat wrapper preserving the (note, vault) signature."""

    return _index_module.index_entry(note_path)


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


# Log writers and event-stream helpers moved to log_writer.py;
# re-exported under the underscore-prefixed names for legacy callers.
try:
    from .log_writer import (
        append_correction_events,
        append_jsonl_events,
        append_log_entries as _append_log_entries,
        append_operation_log,
        append_suggestion_feedback,
        maybe_emit_orphan_correction as _maybe_emit_orphan_correction,
        print_feedback_hint as _print_feedback_hint,
        rotate_operation_log as _rotate_operation_log,
        split_log_entries as _split_log_entries,
    )
except ImportError:  # script-mode fallback
    from log_writer import (  # type: ignore[no-redef]
        append_correction_events,
        append_jsonl_events,
        append_log_entries as _append_log_entries,
        append_operation_log,
        append_suggestion_feedback,
        maybe_emit_orphan_correction as _maybe_emit_orphan_correction,
        print_feedback_hint as _print_feedback_hint,
        rotate_operation_log as _rotate_operation_log,
        split_log_entries as _split_log_entries,
    )


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


# Section update operations now live in section_ops.py; re-export here
# so existing callers (and tests) keep importing from obsidian_writer
# unchanged. Implementations are byte-for-byte identical.
try:
    from .section_ops import (  # noqa: E402
        add_conflict_annotation,
        add_source_reference,
        add_supporting_note,
        update_note_sections,
    )
except ImportError:
    from section_ops import (  # type: ignore[no-redef]  # noqa: E402
        add_conflict_annotation,
        add_source_reference,
        add_supporting_note,
        update_note_sections,
    )


# Index helpers now live in skills.obsidian.index. Thin shims preserve
# the original ``(vault, ...)`` signatures expected by callers.
def rebuild_index(vault: Path) -> Path:
    return _index_module.rebuild_index(vault)


def _append_to_index(vault: Path, note_path: Path, section_name: str) -> None:
    _index_module.append_to_index(vault, note_path, section_name)


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


# Query / organize / lint moved to knowledge_service.py; re-exported
# here under the underscore-prefixed names used by tests and internal
# callers.
try:
    from .knowledge_service import (
        extract_profile_section as _extract_profile_section,
        fix_frontmatter as _fix_frontmatter,
        lint_vault,
        organize_vault,
        profile_query_keywords as _profile_query_keywords,
        query_keywords as _query_keywords,
        query_vault,
        topic_summary_payload as _topic_summary_payload,
    )
except ImportError:  # script-mode fallback
    from knowledge_service import (  # type: ignore[no-redef]
        extract_profile_section as _extract_profile_section,
        fix_frontmatter as _fix_frontmatter,
        lint_vault,
        organize_vault,
        profile_query_keywords as _profile_query_keywords,
        query_keywords as _query_keywords,
        query_vault,
        topic_summary_payload as _topic_summary_payload,
    )



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# parse_args + main moved to cli.py to keep this module focused on
# write/append/init helpers and re-exports. The names are re-exported
# below so existing callers (and ``import skills.obsidian.obsidian_writer
# as ow; ow.main(...)`` in tests) keep working without a code change.
try:
    from .cli import main, parse_args  # noqa: E402,F401
except ImportError:  # script-mode fallback
    from cli import main, parse_args  # type: ignore[no-redef]  # noqa: E402,F401


if __name__ == "__main__":
    main()
