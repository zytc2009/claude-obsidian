"""Tests for skills.obsidian.section_ops.

Covers both the path-based legacy API (parity with the original
obsidian_writer behavior) and the workspace-based API (atomic writes,
path safety inherited from VaultWorkspace).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.obsidian import section_ops
from skills.obsidian.note_repository import NoteRepository
from skills.obsidian.workspace import VaultWorkspace


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------


class TestPureLogic:
    def test_compute_section_updates_replaces_existing(self) -> None:
        text = "---\n---\n# Intro\nold\n# Other\nkeep\n"
        new_text, changed = section_ops.compute_section_updates(
            text, {"Intro": "new"}
        )
        assert "# Intro\nnew\n\n" in new_text
        assert "# Other\nkeep" in new_text
        assert changed == ["Intro"]

    def test_compute_section_updates_appends_when_missing(self) -> None:
        text = "---\n---\nbody\n"
        new_text, changed = section_ops.compute_section_updates(
            text, {"New": "added"}
        )
        assert "# New\nadded" in new_text
        assert changed == ["New"]

    def test_compute_section_updates_empty_fields_returns_unchanged(self) -> None:
        text = "anything"
        new_text, changed = section_ops.compute_section_updates(text, {})
        assert new_text == text and changed == []

    def test_compute_supporting_note_idempotent(self) -> None:
        text = "# Supporting notes\n- [[Foo]]\n"
        out = section_ops.compute_supporting_note(text, "Foo")
        assert out == text

    def test_compute_conflict_returns_none_when_unindented_block_present(
        self,
    ) -> None:
        # The dedupe check is ``block in text`` against the raw joined
        # string (no bullet prefix, no indent), matching the original
        # obsidian_writer behavior.
        joined = (
            "Source: [[A]]\nClaim: x\nConflicts with: y\nStatus: unresolved"
        )
        text = f"# Conflicts\n{joined}\n"
        out = section_ops.compute_conflict_annotation(
            text, "A", "x", "y", "unresolved"
        )
        assert out is None

    def test_compute_conflict_appends_when_absent(self) -> None:
        text = "body\n"
        out = section_ops.compute_conflict_annotation(
            text, "A", "x", "y", "unresolved"
        )
        assert out is not None
        assert "# Conflicts" in out
        assert "Source: [[A]]" in out


# ---------------------------------------------------------------------------
# Path-based legacy API
# ---------------------------------------------------------------------------


class TestPathBasedAPI:
    def test_update_note_sections_writes_file(self, tmp_path: Path) -> None:
        note = tmp_path / "a.md"
        note.write_text("---\n---\n# Intro\nold\n", encoding="utf-8")
        changed = section_ops.update_note_sections(note, {"Intro": "new"})
        assert changed == ["Intro"]
        assert "# Intro\nnew" in note.read_text(encoding="utf-8")

    def test_add_supporting_note_returns_false_when_present(self, tmp_path: Path) -> None:
        note = tmp_path / "a.md"
        note.write_text("# Supporting notes\n- [[Foo]]\n", encoding="utf-8")
        assert section_ops.add_supporting_note(note, "Foo") is False

    def test_add_source_reference_creates_section(self, tmp_path: Path) -> None:
        note = tmp_path / "a.md"
        note.write_text("body\n", encoding="utf-8")
        assert section_ops.add_source_reference(note, "ref-1") is True
        assert "# Sources\n- ref-1" in note.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Workspace-based API
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> NoteRepository:
    root = tmp_path / "vault"
    root.mkdir()
    return NoteRepository(VaultWorkspace(root))


class TestWorkspaceBasedAPI:
    def test_update_sections_writes_atomically(self, repo: NoteRepository) -> None:
        repo.workspace.write_atomic("a.md", "---\n---\n# Intro\nold\n")
        changed = section_ops.update_note_sections_ws(
            repo, "a.md", {"Intro": "new"}
        )
        assert changed == ["Intro"]
        assert "# Intro\nnew" in repo.get_by_path("a.md").text

    def test_update_sections_unchanged_returns_empty(
        self, repo: NoteRepository
    ) -> None:
        repo.workspace.write_atomic("a.md", "body\n")
        # No-op: empty fields.
        assert section_ops.update_note_sections_ws(repo, "a.md", {}) == []

    def test_add_supporting_note_ws(self, repo: NoteRepository) -> None:
        repo.workspace.write_atomic("a.md", "body\n")
        assert (
            section_ops.add_supporting_note_ws(repo, "a.md", "Concept - X")
            is True
        )
        text = repo.get_by_path("a.md").text
        assert "# Supporting notes\n- [[Concept - X]]" in text

    def test_traversal_blocked_through_ws_api(
        self, repo: NoteRepository
    ) -> None:
        from skills.obsidian.workspace import PathOutsideVaultError

        with pytest.raises(PathOutsideVaultError):
            section_ops.update_note_sections_ws(repo, "../escape.md", {"X": "y"})
