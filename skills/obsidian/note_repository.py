"""
note_repository.py — High-level Note view over a vault.

Composes :mod:`workspace` (safe IO + conflict detection) and
:mod:`frontmatter` (parsing) into a Note entity layer. Higher-level
services (knowledge_service, ingest_service, live_note) operate on
``Note`` objects rather than raw paths.

Zero dependencies on ``obsidian_writer`` so this module can be tested
in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePath
from typing import Iterable

try:
    from . import frontmatter as fm
    from .workspace import (
        ConflictError,
        VaultWorkspace,
        WorkspaceError,
        WorkspaceStat,
    )
except ImportError:  # script-mode fallback
    import frontmatter as fm  # type: ignore[no-redef]
    from workspace import (  # type: ignore[no-redef]
        ConflictError,
        VaultWorkspace,
        WorkspaceError,
        WorkspaceStat,
    )

__all__ = [
    "Note",
    "NoteRepository",
    "NoteNotFoundError",
]


class NoteNotFoundError(WorkspaceError):
    """Raised when a note lookup fails."""


@dataclass
class Note:
    """In-memory view of a markdown note inside a vault."""

    rel_path: PurePath
    text: str
    stat: WorkspaceStat

    @property
    def stem(self) -> str:
        return self.rel_path.stem

    @property
    def frontmatter(self) -> dict[str, str]:
        return fm.parse_dict(self.text)

    @property
    def body(self) -> str:
        _, body = fm.parse(self.text)
        return body


@dataclass
class RenameResult:
    note: Note
    backlinks_updated: int
    aliases_updated: int
    files_touched: list[PurePath] = field(default_factory=list)


class NoteRepository:
    """Find, mutate, rename notes through a :class:`VaultWorkspace`."""

    def __init__(self, ws: VaultWorkspace) -> None:
        self._ws = ws

    @property
    def workspace(self) -> VaultWorkspace:
        return self._ws

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def find_by_path(self, rel: str | PurePath) -> Note | None:
        # Validate first so traversal / absolute paths raise instead of
        # silently returning None. Only true "file does not exist"
        # answers None.
        resolved = self._ws.resolve_path(rel)
        if not resolved.exists():
            return None
        text = self._ws.read_text(rel)
        stat = self._ws.stat(rel)
        return Note(rel_path=PurePath(rel), text=text, stat=stat)

    def get_by_path(self, rel: str | PurePath) -> Note:
        note = self.find_by_path(rel)
        if note is None:
            raise NoteNotFoundError(f"Note not found: {rel}")
        return note

    def find_by_stem(self, stem: str) -> Note | None:
        """Return the first note whose filename stem matches ``stem``.

        Search order is filesystem-determined; if multiple notes share
        a stem, callers should use :meth:`find_all_by_stem` instead.
        """

        for path in self._ws.iter_files(pattern=f"{stem}.md"):
            rel = path.relative_to(self._ws.root)
            return self.find_by_path(rel)
        return None

    def find_all_by_stem(self, stem: str) -> list[Note]:
        out: list[Note] = []
        for path in self._ws.iter_files(pattern=f"{stem}.md"):
            rel = path.relative_to(self._ws.root)
            note = self.find_by_path(rel)
            if note is not None:
                out.append(note)
        return out

    def list_in(self, subdir: str | PurePath = "", *, pattern: str = "*.md") -> list[Note]:
        notes: list[Note] = []
        for path in self._ws.iter_files(subdir=subdir, pattern=pattern):
            rel = path.relative_to(self._ws.root)
            note = self.find_by_path(rel)
            if note is not None:
                notes.append(note)
        return notes

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def write(self, note: Note, *, expect_unchanged: bool = True) -> Note:
        """Persist ``note.text`` back to disk.

        When ``expect_unchanged`` is True (the default), the on-disk
        stat must still match ``note.stat`` or a :class:`ConflictError`
        is raised. Pass ``expect_unchanged=False`` after a deliberate
        re-read.
        """

        expect = note.stat if expect_unchanged else None
        new_stat = self._ws.write_atomic(note.rel_path, note.text, expect=expect)
        note.stat = new_stat
        return note

    def update_sections(self, note: Note, fields: dict[str, str]) -> Note:
        """Replace each ``# Title`` section's body with the given content.

        Sections not present in ``fields`` are left untouched. Sections
        that do not yet exist are appended.
        """

        text = note.text
        for title, content in fields.items():
            text = fm.replace_section(text, title, content)
        note.text = text
        return self.write(note)

    def touch_updated(self, note: Note, today: str | None = None) -> Note:
        """Refresh the ``updated`` frontmatter field to today's date."""

        stamp = today or date.today().isoformat()
        new_text = fm.update_field(note.text, "updated", stamp)
        if new_text == note.text:
            return note
        note.text = new_text
        return self.write(note)

    # ------------------------------------------------------------------
    # Rename + backlink rewrite
    # ------------------------------------------------------------------

    def rename(
        self,
        note: Note,
        new_stem: str,
        *,
        preserve_alias: bool = True,
    ) -> RenameResult:
        """Rename ``note`` to ``new_stem`` and rewrite backlinks vault-wide.

        Steps:
          1. Move the markdown file to ``<same dir>/<new_stem>.md``.
          2. Optionally append the old stem to the renamed note's
             ``aliases`` frontmatter (so old wikilinks that we *miss*
             — e.g. inside frontmatter values or fenced code — still
             resolve in Obsidian).
          3. Walk every ``*.md`` in the vault and rewrite
             ``[[old_stem]]``, ``[[old_stem|...]]``, and
             ``[[folder/old_stem...]]`` to use ``new_stem``.

        The renamed note itself is also scanned, in case it contains
        self-references.
        """

        old_stem = note.rel_path.stem
        if new_stem == old_stem:
            return RenameResult(note=note, backlinks_updated=0, aliases_updated=0)

        new_rel = note.rel_path.with_name(f"{new_stem}.md")

        # 1. Optionally bake the old stem into aliases before rename so
        #    a crash mid-rewrite still leaves Obsidian able to resolve.
        aliases_updated = 0
        if preserve_alias:
            new_text = fm.add_alias(note.text, old_stem)
            if new_text != note.text:
                note.text = new_text
                self._ws.write_atomic(note.rel_path, note.text, expect=note.stat)
                note.stat = self._ws.stat(note.rel_path)
                aliases_updated = 1

        # 2. Move the file.
        new_stat = self._ws.rename(note.rel_path, new_rel, expect=note.stat)
        note.rel_path = new_rel
        note.stat = new_stat

        # 3. Rewrite backlinks across the vault, including the renamed
        #    note itself.
        backlinks_updated = 0
        files_touched: list[PurePath] = []
        for path in self._ws.iter_files():
            rel = path.relative_to(self._ws.root)
            text = self._ws.read_text(rel)
            new_text, count = fm.replace_wikilink_target(text, old_stem, new_stem)
            if count == 0:
                continue
            current_stat = self._ws.stat(rel)
            self._ws.write_atomic(rel, new_text, expect=current_stat)
            backlinks_updated += count
            files_touched.append(rel)
            if rel == new_rel:
                # Refresh in-memory note state.
                note.text = new_text
                note.stat = self._ws.stat(rel)

        return RenameResult(
            note=note,
            backlinks_updated=backlinks_updated,
            aliases_updated=aliases_updated,
            files_touched=files_touched,
        )

    # ------------------------------------------------------------------
    # Bulk helpers
    # ------------------------------------------------------------------

    def iter_notes(self, subdir: str | PurePath = "") -> Iterable[Note]:
        for path in self._ws.iter_files(subdir=subdir):
            rel = path.relative_to(self._ws.root)
            note = self.find_by_path(rel)
            if note is not None:
                yield note
