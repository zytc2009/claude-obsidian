"""
log_writer.py — Vault-level log and event-stream writers.

Owns the three observability files at the vault root:

  - ``_log.md`` — human-readable operation log (rotating to
    ``_log.archive.md`` after :data:`MAX_LOG_ENTRIES`)
  - ``_corrections.jsonl`` — lint findings as machine-readable events
  - ``_events.jsonl`` — suggestion feedback (reject / modify-accept)
    and other domain events

Public API mirrors the helper names previously defined inline in
``obsidian_writer``; the original underscore-prefixed names are
re-exported there for backward compatibility.

This module is dependency-light by design: it only imports ``json``
and ``pathlib`` from stdlib and lazily probes ``SessionMemory`` so it
can be used without optional dependencies.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

LOG_FILE = "_log.md"
LOG_ARCHIVE_FILE = "_log.archive.md"
CORRECTIONS_FILE = "_corrections.jsonl"
EVENTS_FILE = "_events.jsonl"
MAX_LOG_ENTRIES = 500


# ---------------------------------------------------------------------------
# Local helpers (kept private; duplicated from obsidian_writer to avoid
# importing back from it and forming a circular dependency).
# ---------------------------------------------------------------------------


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _safe_session_memory(vault: Path):
    """Return a SessionMemory if the optional module is available."""

    try:
        try:
            from .session_memory import SessionMemory
        except ImportError:
            from session_memory import SessionMemory  # type: ignore[no-redef]
    except ImportError:
        return None
    try:
        return SessionMemory(vault, persist=True)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Feedback target normalization
# ---------------------------------------------------------------------------


def normalize_feedback_target(target: str) -> str:
    """Normalize a feedback target to its note stem.

    Used to keep suggestion hints and feedback scoring keyed
    consistently regardless of whether the caller passed a stem or a
    full ``.md`` path.
    """

    target_name = str(target).strip()
    if not target_name:
        return ""
    target_path = Path(target_name)
    return target_path.stem.strip() or target_name


# ---------------------------------------------------------------------------
# Operation log (markdown, rotating)
# ---------------------------------------------------------------------------


def split_log_entries(text: str) -> tuple[str, list[str]]:
    """Split a markdown log file into header text and individual entries."""

    marker = "\n## ["
    if marker not in text:
        return text.rstrip("\n"), []
    start = text.index(marker)
    header = text[:start].rstrip("\n")
    body = text[start + 1:]
    raw_entries = body.split(marker)
    entries = []
    for i, chunk in enumerate(raw_entries):
        entry = chunk if i == 0 else f"## [{chunk}"
        entries.append(entry.strip("\n"))
    return header, [entry for entry in entries if entry]


def append_log_entries(log_path: Path, header: str, entries: list[str]) -> None:
    """Write a markdown log file from a header and entry list."""

    _ensure_parent(log_path)
    text = header.rstrip("\n")
    if entries:
        text += "\n\n" + "\n\n".join(entry.strip("\n") for entry in entries) + "\n"
    else:
        text += "\n"
    log_path.write_text(text, encoding="utf-8")


def rotate_operation_log(vault: Path) -> None:
    """Rotate older operation-log entries into an archive file."""

    log_path = vault / LOG_FILE
    if not log_path.exists():
        return

    header, entries = split_log_entries(
        log_path.read_text(encoding="utf-8", errors="replace")
    )
    if len(entries) <= MAX_LOG_ENTRIES:
        return

    archive_path = vault / LOG_ARCHIVE_FILE
    overflow = entries[:-MAX_LOG_ENTRIES]
    kept = entries[-MAX_LOG_ENTRIES:]

    if archive_path.exists():
        archive_header, archive_entries = split_log_entries(
            archive_path.read_text(encoding="utf-8", errors="replace")
        )
    else:
        archive_header, archive_entries = ("# Vault Operation Log Archive", [])

    archive_entries.extend(overflow)
    append_log_entries(archive_path, archive_header, archive_entries)
    append_log_entries(log_path, header or "# Vault Operation Log", kept)


def append_operation_log(
    vault: Path,
    operation: str,
    title: str = "",
    details: list[str] | None = None,
) -> Path:
    """Append an operation entry to the vault log, rotating if needed."""

    log_path = vault / LOG_FILE
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
    rotate_operation_log(vault)
    return log_path


# ---------------------------------------------------------------------------
# JSONL event streams (corrections, events)
# ---------------------------------------------------------------------------


def append_correction_events(vault: Path, events: list[dict]) -> Path | None:
    """Append lint findings as JSONL correction events."""

    if not events:
        return None
    corrections_path = vault / CORRECTIONS_FILE
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
    """Record a suggestion-feedback event and mirror it into the operation log."""

    normalized_targets: list[str] = []
    for target in target_notes:
        normalized = normalize_feedback_target(target)
        if normalized:
            normalized_targets.append(normalized)

    event: dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "event_type": "suggestion_feedback",
        "suggestion_type": suggestion_type,
        "source_note": source_note,
        "target_notes": normalized_targets,
        "action": action,
        "reason": reason,
    }
    events_path = vault / EVENTS_FILE
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


# ---------------------------------------------------------------------------
# Side channels: orphan warning, feedback CLI hint
# ---------------------------------------------------------------------------


def maybe_emit_orphan_correction(
    vault: Path,
    filepath: Path,
    suggestions: list,
    is_draft: bool,
) -> None:
    """Emit an orphan-on-create correction if the note has no topic parent."""

    if is_draft:
        return
    try:
        rel = filepath.relative_to(vault)
    except ValueError:
        return
    if rel.parts[0] != "03-Knowledge":
        return

    has_topic = any("Topics" in str(rel) for rel, _ in suggestions)
    if has_topic:
        return

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
    print(
        "[Orphan warning] This note has no topic parent. Consider attaching it to a topic."
    )


def print_feedback_hint(
    source_note: str,
    suggestion_type: str,
    targets: list[str],
    reason: str = "",
    *,
    script_path: Path | None = None,
) -> None:
    """Print a copyable feedback command hint.

    ``script_path`` defaults to the original ``obsidian_writer.py``
    path so that the printed command remains directly runnable for
    legacy callers; pass an explicit path for new entry points.
    """

    if not source_note or not suggestion_type:
        return

    if script_path is None:
        # Best effort: locate the legacy entry point in this package.
        script_path = (Path(__file__).resolve().parent / "obsidian_writer.py")

    normalized_targets: list[str] = []
    for target in targets:
        normalized = normalize_feedback_target(target)
        if normalized:
            normalized_targets.append(normalized)
    joined_targets = ",".join(normalized_targets)

    print("\n[Feedback hint]")
    print("  Record a rejection or modified acceptance with:")
    print(
        f'  python "{script_path}" '
        f'--type suggestion-feedback --source-note "{source_note}" '
        f'--suggestion-type {suggestion_type} --feedback-action reject|modify-accept '
        f'--targets "{joined_targets}"'
    )
    if reason:
        print(f"  Reason: {reason}")
