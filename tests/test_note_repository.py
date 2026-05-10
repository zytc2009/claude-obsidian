"""Tests for skills.obsidian.note_repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.obsidian import frontmatter as fm
from skills.obsidian.note_repository import (
    Note,
    NoteNotFoundError,
    NoteRepository,
)
from skills.obsidian.workspace import (
    ConflictError,
    VaultWorkspace,
    WorkspaceStat,
)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    return root


@pytest.fixture
def repo(vault: Path) -> NoteRepository:
    ws = VaultWorkspace(vault)
    return NoteRepository(ws)


def _seed(repo: NoteRepository, rel: str, text: str) -> Note:
    repo.workspace.write_atomic(rel, text)
    return repo.get_by_path(rel)


class TestLookup:
    def test_find_by_path_returns_none_when_missing(self, repo: NoteRepository) -> None:
        assert repo.find_by_path("nope.md") is None

    def test_get_by_path_raises_when_missing(self, repo: NoteRepository) -> None:
        with pytest.raises(NoteNotFoundError):
            repo.get_by_path("nope.md")

    def test_find_by_stem_searches_subdirs(self, repo: NoteRepository) -> None:
        repo.workspace.write_atomic("notes/Foo.md", "x")
        found = repo.find_by_stem("Foo")
        assert found is not None
        assert found.stem == "Foo"
        assert found.rel_path.parts[0] == "notes"

    def test_list_in_subdir(self, repo: NoteRepository) -> None:
        repo.workspace.write_atomic("a/x.md", "1")
        repo.workspace.write_atomic("b/y.md", "2")
        names = sorted(n.stem for n in repo.list_in("a"))
        assert names == ["x"]


class TestNoteAccessors:
    def test_frontmatter_and_body(self, repo: NoteRepository) -> None:
        note = _seed(repo, "a.md", "---\ntitle: Foo\n---\nhello\n")
        assert note.frontmatter == {"title": "Foo"}
        assert note.body == "hello\n"


class TestUpdateSections:
    def test_replaces_section_body(self, repo: NoteRepository) -> None:
        note = _seed(
            repo,
            "a.md",
            "---\ntitle: Foo\n---\n# Intro\nold\n# Other\nkeep\n",
        )
        repo.update_sections(note, {"Intro": "new"})
        text = repo.get_by_path("a.md").text
        assert "# Intro\nnew\n" in text
        assert "# Other\nkeep" in text

    def test_appends_when_section_missing(self, repo: NoteRepository) -> None:
        note = _seed(repo, "a.md", "---\n---\nbody\n")
        repo.update_sections(note, {"New": "added"})
        text = repo.get_by_path("a.md").text
        assert "# New\nadded\n" in text


class TestWriteConflict:
    def test_concurrent_modification_raises(self, repo: NoteRepository) -> None:
        note = _seed(repo, "a.md", "v1")
        # External writer changes the file.
        repo.workspace.write_atomic("a.md", "external")
        # The cached Note still points to the original stat.
        with pytest.raises(ConflictError):
            repo.update_sections(note, {"X": "y"})

    def test_re_read_resolves_conflict(self, repo: NoteRepository) -> None:
        _seed(repo, "a.md", "v1")
        repo.workspace.write_atomic("a.md", "external")
        note = repo.get_by_path("a.md")
        repo.update_sections(note, {"X": "y"})  # uses fresh stat
        assert "# X\ny\n" in repo.get_by_path("a.md").text


class TestRename:
    def test_rename_moves_file(self, repo: NoteRepository, vault: Path) -> None:
        note = _seed(repo, "Old.md", "---\n---\nbody\n")
        result = repo.rename(note, "New")
        assert not (vault / "Old.md").exists()
        assert (vault / "New.md").exists()
        assert result.note.stem == "New"

    def test_rename_rewrites_plain_backlinks(
        self, repo: NoteRepository
    ) -> None:
        _seed(repo, "Other.md", "---\n---\nrefers to [[Old]] here.\n")
        note = _seed(repo, "Old.md", "---\n---\nbody\n")
        result = repo.rename(note, "New")
        assert "[[New]]" in repo.get_by_path("Other.md").text
        assert "[[Old]]" not in repo.get_by_path("Other.md").text
        assert result.backlinks_updated >= 1

    def test_rename_rewrites_alias_form(self, repo: NoteRepository) -> None:
        _seed(repo, "Other.md", "---\n---\n[[Old|Display]]\n")
        note = _seed(repo, "Old.md", "---\n---\nbody\n")
        repo.rename(note, "New")
        assert "[[New|Display]]" in repo.get_by_path("Other.md").text

    def test_rename_rewrites_heading_form(self, repo: NoteRepository) -> None:
        _seed(repo, "Other.md", "---\n---\n[[Old#Section]]\n")
        note = _seed(repo, "Old.md", "---\n---\nbody\n")
        repo.rename(note, "New")
        assert "[[New#Section]]" in repo.get_by_path("Other.md").text

    def test_rename_rewrites_folder_prefixed(self, repo: NoteRepository) -> None:
        _seed(repo, "Other.md", "---\n---\n[[03-Knowledge/Topics/Old]]\n")
        note = _seed(repo, "03-Knowledge/Topics/Old.md", "---\n---\nbody\n")
        repo.rename(note, "New")
        text = repo.get_by_path("Other.md").text
        assert "[[03-Knowledge/Topics/New]]" in text

    def test_rename_does_not_touch_unrelated_links(
        self, repo: NoteRepository
    ) -> None:
        _seed(repo, "Other.md", "---\n---\n[[Unrelated]]\n")
        note = _seed(repo, "Old.md", "---\n---\nbody\n")
        repo.rename(note, "New")
        assert "[[Unrelated]]" in repo.get_by_path("Other.md").text

    def test_rename_appends_old_stem_to_aliases(
        self, repo: NoteRepository
    ) -> None:
        note = _seed(repo, "Old.md", "---\ntitle: Foo\n---\nbody\n")
        repo.rename(note, "New")
        renamed = repo.get_by_path("New.md")
        aliases = fm.extract_aliases(renamed.frontmatter)
        assert "Old" in aliases

    def test_rename_alias_preservation_can_be_disabled(
        self, repo: NoteRepository
    ) -> None:
        note = _seed(repo, "Old.md", "---\ntitle: Foo\n---\nbody\n")
        repo.rename(note, "New", preserve_alias=False)
        renamed = repo.get_by_path("New.md")
        assert "aliases" not in renamed.frontmatter

    def test_rename_no_op_when_same_stem(self, repo: NoteRepository) -> None:
        note = _seed(repo, "Same.md", "---\n---\nbody\n")
        result = repo.rename(note, "Same")
        assert result.backlinks_updated == 0
        assert result.aliases_updated == 0


class TestTouchUpdated:
    def test_sets_updated_field(self, repo: NoteRepository) -> None:
        note = _seed(repo, "a.md", "---\ntitle: Foo\n---\nbody\n")
        repo.touch_updated(note, today="2026-05-10")
        assert "updated: 2026-05-10" in repo.get_by_path("a.md").text
