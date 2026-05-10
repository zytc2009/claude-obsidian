"""End-to-end tests across workspace + frontmatter + note_repository.

These tests don't import obsidian_writer; they verify the new layered
stack works on its own and that the safety properties hold against
realistic attack vectors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.obsidian.note_repository import NoteRepository
from skills.obsidian.workspace import (
    ConflictError,
    PathOutsideVaultError,
    VaultWorkspace,
)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    return root


@pytest.fixture
def repo(vault: Path) -> NoteRepository:
    return NoteRepository(VaultWorkspace(vault))


class TestRenameRoundTrip:
    def test_rename_updates_all_backlink_forms_at_once(
        self, repo: NoteRepository
    ) -> None:
        repo.workspace.write_atomic(
            "Hub.md",
            "---\n---\n"
            "see [[Old]], [[Old|alias]], [[Old#Section]], "
            "[[03-Knowledge/Topics/Old]]\n"
            "and unrelated [[Other]].\n",
        )
        repo.workspace.write_atomic(
            "03-Knowledge/Topics/Old.md", "---\n---\nbody\n"
        )

        note = repo.get_by_path("03-Knowledge/Topics/Old.md")
        result = repo.rename(note, "New")

        hub_text = repo.get_by_path("Hub.md").text
        assert "[[New]]" in hub_text
        assert "[[New|alias]]" in hub_text
        assert "[[New#Section]]" in hub_text
        assert "[[03-Knowledge/Topics/New]]" in hub_text
        assert "[[Other]]" in hub_text
        assert "Old" not in hub_text.replace("Other", "")
        assert result.backlinks_updated == 4


class TestConflictDetectionEndToEnd:
    def test_external_modification_blocks_stale_write(
        self, repo: NoteRepository
    ) -> None:
        repo.workspace.write_atomic("a.md", "v1")
        note = repo.get_by_path("a.md")

        # Simulate Obsidian client editing the file out from under us.
        repo.workspace.write_atomic("a.md", "obsidian-edit")

        with pytest.raises(ConflictError):
            repo.update_sections(note, {"X": "mine"})

        # The Obsidian edit should still be on disk.
        assert repo.get_by_path("a.md").text == "obsidian-edit"


class TestTraversalAttacks:
    @pytest.mark.parametrize(
        "evil",
        [
            "../escape.md",
            "notes/../../../escape.md",
            "./../../escape.md",
        ],
    )
    def test_traversal_inputs_blocked_at_workspace_layer(
        self, repo: NoteRepository, evil: str
    ) -> None:
        with pytest.raises(PathOutsideVaultError):
            repo.find_by_path(evil)

    def test_absolute_path_blocked(
        self, repo: NoteRepository, tmp_path: Path
    ) -> None:
        with pytest.raises(PathOutsideVaultError):
            repo.find_by_path(str(tmp_path / "anywhere.md"))


class TestTrashRecoverable:
    def test_trashed_file_remains_readable_outside_vault(
        self, repo: NoteRepository, vault: Path
    ) -> None:
        repo.workspace.write_atomic("doomed.md", "important content")
        trashed = repo.workspace.move_to_trash("doomed.md")

        # Outside the vault, but readable for manual recovery.
        assert vault not in trashed.parents
        assert trashed.read_text(encoding="utf-8") == "important content"

        # And iter_files no longer yields it.
        names = [p.name for p in repo.workspace.iter_files()]
        assert "doomed.md" not in names
