"""
ingest_service.py — Capture, merge, and cascade orchestration.

Owns the deterministic ingest plan executor (:func:`run_ingest_sync`)
and the candidate-finding helpers used by the upstream ingest UI:

  - :func:`classify_ingest_action` — dry-run preview of where a write
    would land and whether it would collide
  - :func:`find_merge_candidates` — literature notes whose title/body
    overlap with a new title
  - :func:`find_cascade_candidates` — topic notes that should pick up
    cascade updates from a new note

Composes :mod:`section_ops`, :mod:`linker`, :mod:`log_writer`,
:mod:`templates`, and :mod:`frontmatter` — does not import back from
``obsidian_writer``, keeping the dependency graph one-directional.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

try:
    from . import frontmatter as fm
    from .linker import suggest_links, suggestion_keywords_from_stem
    from .log_writer import _safe_session_memory, append_operation_log
    from .section_ops import (
        add_conflict_annotation,
        add_source_reference,
        add_supporting_note,
        update_note_sections,
    )
    from .templates import NOTE_CONFIG, get_target_path
except ImportError:  # script-mode fallback
    import frontmatter as fm  # type: ignore[no-redef]
    from linker import suggest_links, suggestion_keywords_from_stem  # type: ignore[no-redef]
    from log_writer import _safe_session_memory, append_operation_log  # type: ignore[no-redef]
    from section_ops import (  # type: ignore[no-redef]
        add_conflict_annotation,
        add_source_reference,
        add_supporting_note,
        update_note_sections,
    )
    from templates import NOTE_CONFIG, get_target_path  # type: ignore[no-redef]


# Fields that may be updated during a topic cascade (matches the
# topic note template structure).
TOPIC_CASCADE_FIELDS = {
    "主题说明", "核心问题", "重要资料", "相关项目", "当前结论", "未解决问题",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def _touch_updated(path: Path) -> bool:
    """Refresh the ``updated`` frontmatter field to today's date."""

    text = path.read_text(encoding="utf-8", errors="replace")
    new_text = fm.update_field(text, "updated", _today_str())
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


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


def resolve_vault_path(vault: Path, target_arg: str) -> Path:
    """Resolve ``target_arg`` to an absolute path, scoped to ``vault`` if relative.

    Note: this is a *resolution* helper used by ingest plans that
    accept either absolute or vault-relative paths. It does NOT
    enforce the vault boundary — the caller's ``Path.exists()``
    check is the gate. Use :class:`workspace.VaultWorkspace` when
    boundary enforcement matters.
    """

    path = Path(target_arg)
    if not path.is_absolute():
        path = vault / path
    return path


# ---------------------------------------------------------------------------
# Classification / preview
# ---------------------------------------------------------------------------


def classify_ingest_action(
    vault: Path, note_type: str, title: str, is_draft: bool
) -> tuple[str, "Path | None", Path]:
    """Return ``(action, existing_path_or_None, planned_write_path)``.

    Action values:
      - ``"create"`` — no collision, net-new note
      - ``"create (dated copy)"`` — base filename exists; existing
        note is unchanged, a new dated copy will be written instead
    """

    target_dir = get_target_path(vault, note_type, is_draft)
    prefix = NOTE_CONFIG[note_type]["prefix"]
    base_path = target_dir / f"{prefix} - {title}.md"

    if not base_path.exists():
        return "create", None, base_path

    today = _today_str()
    dated_path = target_dir / f"{prefix} - {title} {today}.md"
    return "create (dated copy)", base_path, dated_path


def section_diff_summary(existing_path: Path, new_content: str) -> str:
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


def normalize_title(title: str) -> str:
    """Normalize a title for similarity comparison (article duplicate detection)."""

    cleaned = title or ""
    cleaned = re.sub(
        r"^(Article|Literature|Concept|Topic|Project|MOC)\s*[-–—]?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s\d{4}-\d{2}-\d{2}$", "", cleaned)
    cleaned = re.sub(r"[^\w\s一-鿿]", "", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned.lower().strip()


def check_duplicate(vault: Path, note_type: str, title: str) -> Path | None:
    """Return an existing similar note for article writes (≥0.8 ratio), if any."""

    if note_type != "article":
        return None
    import difflib

    target_dir = vault / NOTE_CONFIG[note_type]["target"]
    if not target_dir.exists():
        return None

    candidate = normalize_title(title)
    for existing in target_dir.glob("*.md"):
        existing_norm = normalize_title(existing.stem)
        ratio = difflib.SequenceMatcher(None, candidate, existing_norm).ratio()
        if ratio >= 0.8:
            return existing
    return None


# ---------------------------------------------------------------------------
# Candidate finders
# ---------------------------------------------------------------------------


def find_merge_candidates(vault: Path, title: str, limit: int = 5) -> list[Path]:
    """Return likely literature merge candidates based on title keyword overlap."""

    literature_dir = vault / "03-Knowledge/Literature"
    if not literature_dir.exists():
        return []

    keywords = [w.lower() for w in suggestion_keywords_from_stem(title)]
    if not keywords:
        keywords = [w.lower() for w in re.split(r"[\s\-_]+", title) if len(w) >= 4]
    if not keywords:
        return []

    scored: list[tuple[int, Path]] = []
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


def find_cascade_candidates(
    vault: Path, note_path: Path, limit: int = 3
) -> list[tuple[Path, str]]:
    """Return likely topic notes for narrow cascade updates."""

    suggestions = suggest_links(vault, note_path)
    candidates: list[tuple[Path, str]] = []
    for rel, reason in suggestions:
        rel_path = Path(rel)
        if "Topics" not in rel_path.parts:
            continue
        candidates.append((vault / rel_path, reason))
    return candidates[:limit]


# ---------------------------------------------------------------------------
# Plan executor
# ---------------------------------------------------------------------------


def run_ingest_sync(vault: Path, target_path: Path, plan: dict) -> dict:
    """Apply a deterministic ingest plan in one shot.

    Expected plan shape::

        {
          "primary_fields": {...},
          "source_note": "...",
          "source_ref": "...",
          "cascade_updates": [
            {"target": "...", "fields": {...}, "source_note": "..."}
          ],
          "conflicts": [
            {"target": "...", "claim": "...", "conflicts_with": "...",
             "source_note": "...", "status": "..."}
          ]
        }
    """

    if not target_path.exists():
        raise FileNotFoundError(f"target note not found: {target_path}")

    summary: dict = {
        "primary_updates": [],
        "cascade_updates": [],
        "conflicts": [],
    }

    primary_fields = plan.get("primary_fields") or {}
    source_note = (plan.get("source_note") or "").strip()
    source_ref = (plan.get("source_ref") or "").strip()
    primary_changes: list[str] = []
    changed_sections = update_note_sections(target_path, primary_fields)
    if changed_sections:
        primary_changes.append(f"Sections updated: {', '.join(changed_sections)}")
    if source_note and add_supporting_note(target_path, source_note):
        primary_changes.append(f"Supporting note: [[{source_note}]]")
    if source_ref and add_source_reference(target_path, source_ref):
        primary_changes.append(f"Source added: {source_ref}")
    if primary_changes:
        _touch_updated(target_path)
        primary_changes.append(f"Updated date: {_today_str()}")
        _record_session_note(
            vault,
            "topic" if "Topics" in target_path.parts else "note",
            target_path,
        )
    summary["primary_updates"] = primary_changes

    for cascade in plan.get("cascade_updates") or []:
        cascade_target = resolve_vault_path(vault, cascade.get("target", ""))
        if not cascade_target.exists():
            raise FileNotFoundError(f"cascade target not found: {cascade_target}")
        cascade_fields = cascade.get("fields") or {}
        invalid = [k for k in cascade_fields if k not in TOPIC_CASCADE_FIELDS]
        if invalid:
            raise ValueError(
                f"cascade-update only supports topic fields: {', '.join(invalid)}"
            )
        cascade_note = (cascade.get("source_note") or source_note).strip()
        cascade_changes: list[str] = []
        changed_sections = update_note_sections(cascade_target, cascade_fields)
        if changed_sections:
            cascade_changes.append(f"Sections updated: {', '.join(changed_sections)}")
        if cascade_note and add_supporting_note(cascade_target, cascade_note):
            cascade_changes.append(f"Supporting note: [[{cascade_note}]]")
        if cascade_changes:
            _touch_updated(cascade_target)
            cascade_changes.append(f"Updated date: {_today_str()}")
            _record_session_note(vault, "topic", cascade_target)
            summary["cascade_updates"].append(
                {
                    "target": str(cascade_target.relative_to(vault)),
                    "details": cascade_changes,
                }
            )

    for conflict in plan.get("conflicts") or []:
        conflict_target = resolve_vault_path(vault, conflict.get("target", ""))
        if not conflict_target.exists():
            raise FileNotFoundError(f"conflict target not found: {conflict_target}")
        conflict_source = (conflict.get("source_note") or source_note).strip()
        claim = (conflict.get("claim") or "").strip()
        conflicts_with = (conflict.get("conflicts_with") or "").strip()
        status = (conflict.get("status") or "unresolved").strip()
        if not conflict_source or not claim or not conflicts_with:
            raise ValueError(
                "conflict entries require source_note, claim, and conflicts_with"
            )
        changed = add_conflict_annotation(
            conflict_target, conflict_source, claim, conflicts_with, status
        )
        details = [
            f"Conflict source: [[{conflict_source}]]",
            f"Conflicts with: {conflicts_with}",
            f"Status: {status}",
        ]
        if changed:
            _touch_updated(conflict_target)
            details.insert(0, "Conflict added")
            details.append(f"Updated date: {_today_str()}")
            _record_session_note(
                vault,
                "topic" if "Topics" in conflict_target.parts else "note",
                conflict_target,
            )
        else:
            details.insert(0, "Conflict already present")
        summary["conflicts"].append(
            {
                "target": str(conflict_target.relative_to(vault)),
                "details": details,
            }
        )

    log_details: list[str] = []
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
