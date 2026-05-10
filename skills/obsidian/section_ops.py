"""
section_ops.py — Section update operations on Obsidian markdown notes.

Provides two surfaces for the same operations:

  - **Path-based legacy API** preserves the byte-for-byte behavior of
    ``obsidian_writer``'s direct ``Path.read_text``/``write_text``
    helpers, so existing callers keep working without migration.
  - **Workspace-based API** runs the same updates through
    :class:`workspace.VaultWorkspace`, gaining atomic writes, path
    safety, and (optional) conflict detection.

The shared logic lives in pure functions named ``compute_*``: text in,
text out, no IO. Callers pick the IO layer.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    from . import frontmatter as fm
    from .note_repository import NoteRepository
    from .workspace import VaultWorkspace
except ImportError:  # script-mode fallback
    import frontmatter as fm  # type: ignore[no-redef]
    from note_repository import NoteRepository  # type: ignore[no-redef]
    from workspace import VaultWorkspace  # type: ignore[no-redef]

# Section heading constants kept in sync with ``obsidian_writer``.
SUPPORTING_SECTION_TITLE = "# Supporting notes"
SOURCES_SECTION_TITLE = "# Sources"
CONFLICTS_SECTION_TITLE = "# Conflicts"


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------


def compute_section_updates(
    text: str, fields: dict[str, str]
) -> tuple[str, list[str]]:
    """Apply ``fields`` as ``# Heading``-keyed section replacements.

    Behavior parity with ``obsidian_writer.update_note_sections``:
      - matches via ``(?ms)^# {key}\\n(.*?)(?=^# |\\Z)``
      - existing section: replace heading + body, leaving a single
        blank line of separation
      - missing section: append at the end (with one blank line of
        separation if the file does not already end with newline)

    Returns ``(new_text, changed_section_keys)``.
    """

    if not fields:
        return text, []

    changed: list[str] = []
    for key, value in fields.items():
        section_title = f"# {key}"
        replacement = str(value).strip()
        pattern = rf"(?ms)^# {re.escape(key)}\n(.*?)(?=^# |\Z)"
        replacement_block = f"{section_title}\n{replacement}\n\n"
        new_text, count = re.subn(pattern, replacement_block, text)
        if count:
            if new_text != text:
                text = new_text
                changed.append(key)
            continue

        if text.endswith("\n"):
            text = text.rstrip("\n")
        text = f"{text}\n\n{section_title}\n{replacement}\n"
        changed.append(key)

    return text, changed


def compute_supporting_note(text: str, supporting_note_stem: str) -> str:
    """Add a supporting-note wikilink under ``# Supporting notes``."""

    return fm.append_bullet_to_section(
        text, SUPPORTING_SECTION_TITLE, f"[[{supporting_note_stem}]]"
    )


def compute_source_reference(text: str, source_label: str) -> str:
    """Add a source reference under ``# Sources``."""

    return fm.append_bullet_to_section(text, SOURCES_SECTION_TITLE, source_label)


def compute_conflict_annotation(
    text: str,
    source_note: str,
    claim: str,
    conflicts_with: str,
    status: str = "unresolved",
) -> str | None:
    """Append a conflict entry; returns ``None`` if entry already present."""

    source_line = f"Source: [[{source_note}]]"
    claim_line = f"Claim: {claim.strip()}"
    conflicts_line = f"Conflicts with: {conflicts_with.strip()}"
    status_line = f"Status: {status.strip() or 'unresolved'}"
    block = "\n".join([source_line, claim_line, conflicts_line, status_line])

    if block in text:
        return None

    return fm.append_bullet_to_section(
        text,
        CONFLICTS_SECTION_TITLE,
        f"{source_line}\n  {claim_line}\n  {conflicts_line}\n  {status_line}",
    )


# ---------------------------------------------------------------------------
# Path-based legacy API (used by obsidian_writer thin shims)
# ---------------------------------------------------------------------------


def update_note_sections(note_path: Path, fields: dict) -> list[str]:
    """Path-based wrapper. Behavior parity with ``obsidian_writer``."""

    if not fields:
        return []
    text = note_path.read_text(encoding="utf-8", errors="replace")
    new_text, changed = compute_section_updates(text, fields)
    note_path.write_text(new_text, encoding="utf-8")
    return changed


def add_supporting_note(note_path: Path, supporting_note_stem: str) -> bool:
    text = note_path.read_text(encoding="utf-8", errors="replace")
    updated = compute_supporting_note(text, supporting_note_stem)
    if updated == text:
        return False
    note_path.write_text(updated, encoding="utf-8")
    return True


def add_source_reference(note_path: Path, source_label: str) -> bool:
    text = note_path.read_text(encoding="utf-8", errors="replace")
    updated = compute_source_reference(text, source_label)
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
    text = note_path.read_text(encoding="utf-8", errors="replace")
    updated = compute_conflict_annotation(
        text, source_note, claim, conflicts_with, status
    )
    if updated is None or updated == text:
        return False
    note_path.write_text(updated, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Workspace-based API (atomic + path-safe)
# ---------------------------------------------------------------------------


def update_note_sections_ws(
    repo: NoteRepository, rel_path: str, fields: dict
) -> list[str]:
    """Workspace variant of :func:`update_note_sections`.

    Reads and writes through the workspace, so writes are atomic and
    paths are constrained to the vault.
    """

    if not fields:
        return []
    note = repo.get_by_path(rel_path)
    new_text, changed = compute_section_updates(note.text, fields)
    if not changed:
        return []
    note.text = new_text
    repo.write(note)
    return changed


def add_supporting_note_ws(
    repo: NoteRepository, rel_path: str, supporting_note_stem: str
) -> bool:
    note = repo.get_by_path(rel_path)
    updated = compute_supporting_note(note.text, supporting_note_stem)
    if updated == note.text:
        return False
    note.text = updated
    repo.write(note)
    return True


def add_source_reference_ws(
    repo: NoteRepository, rel_path: str, source_label: str
) -> bool:
    note = repo.get_by_path(rel_path)
    updated = compute_source_reference(note.text, source_label)
    if updated == note.text:
        return False
    note.text = updated
    repo.write(note)
    return True


def add_conflict_annotation_ws(
    repo: NoteRepository,
    rel_path: str,
    source_note: str,
    claim: str,
    conflicts_with: str,
    status: str = "unresolved",
) -> bool:
    note = repo.get_by_path(rel_path)
    updated = compute_conflict_annotation(
        note.text, source_note, claim, conflicts_with, status
    )
    if updated is None or updated == note.text:
        return False
    note.text = updated
    repo.write(note)
    return True
