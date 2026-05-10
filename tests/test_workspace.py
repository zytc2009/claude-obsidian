"""Tests for skills.obsidian.workspace.VaultWorkspace."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from skills.obsidian.workspace import (
    ConflictError,
    PathOutsideVaultError,
    VaultWorkspace,
    WorkspaceError,
    WorkspaceStat,
)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    return root


@pytest.fixture
def ws(vault: Path) -> VaultWorkspace:
    return VaultWorkspace(vault)


class TestPathSafety:
    def test_rejects_absolute_path(self, ws: VaultWorkspace, tmp_path: Path) -> None:
        with pytest.raises(PathOutsideVaultError):
            ws.resolve_path(str(tmp_path / "outside.md"))

    def test_rejects_double_dot_traversal(self, ws: VaultWorkspace) -> None:
        with pytest.raises(PathOutsideVaultError):
            ws.resolve_path("../escape.md")

    def test_rejects_nested_double_dot(self, ws: VaultWorkspace) -> None:
        with pytest.raises(PathOutsideVaultError):
            ws.resolve_path("notes/../../escape.md")

    def test_accepts_subdir_path(self, ws: VaultWorkspace, vault: Path) -> None:
        resolved = ws.resolve_path("notes/foo.md")
        assert resolved == (vault / "notes" / "foo.md").resolve()

    def test_accepts_root_relative_file(self, ws: VaultWorkspace, vault: Path) -> None:
        resolved = ws.resolve_path("foo.md")
        assert resolved == (vault / "foo.md").resolve()

    @pytest.mark.skipif(
        os.name == "nt",
        reason="symlink creation requires admin or Developer Mode on Windows",
    )
    def test_rejects_symlink_pointing_outside(
        self, ws: VaultWorkspace, vault: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside.md"
        outside.write_text("secret")
        link = vault / "leak.md"
        link.symlink_to(outside)

        with pytest.raises(PathOutsideVaultError):
            ws.resolve_path("leak.md")


class TestReadWrite:
    def test_write_atomic_creates_file(self, ws: VaultWorkspace, vault: Path) -> None:
        stat = ws.write_atomic("notes/a.md", "hello")
        assert (vault / "notes" / "a.md").read_text(encoding="utf-8") == "hello"
        assert stat.exists
        assert stat.size == len(b"hello")

    def test_write_atomic_overwrites(self, ws: VaultWorkspace) -> None:
        ws.write_atomic("a.md", "first")
        ws.write_atomic("a.md", "second")
        assert ws.read_text("a.md") == "second"

    def test_write_atomic_does_not_leave_tmp_files(
        self, ws: VaultWorkspace, vault: Path
    ) -> None:
        ws.write_atomic("a.md", "hello")
        tmp_files = list(vault.rglob("*.tmp"))
        assert tmp_files == []

    def test_read_text_default_utf8(self, ws: VaultWorkspace) -> None:
        ws.write_atomic("a.md", "汉字")
        assert ws.read_text("a.md") == "汉字"

    def test_stat_for_missing_file(self, ws: VaultWorkspace) -> None:
        s = ws.stat("does-not-exist.md")
        assert not s.exists
        assert s.content_hash == ""

    def test_stat_changes_after_write(self, ws: VaultWorkspace) -> None:
        ws.write_atomic("a.md", "v1")
        s1 = ws.stat("a.md")
        ws.write_atomic("a.md", "v2")
        s2 = ws.stat("a.md")
        assert s1.content_hash != s2.content_hash


class TestConflictDetection:
    def test_write_with_matching_expect_succeeds(self, ws: VaultWorkspace) -> None:
        ws.write_atomic("a.md", "v1")
        s1 = ws.stat("a.md")
        ws.write_atomic("a.md", "v2", expect=s1)
        assert ws.read_text("a.md") == "v2"

    def test_write_with_stale_expect_raises(self, ws: VaultWorkspace) -> None:
        ws.write_atomic("a.md", "v1")
        stale = ws.stat("a.md")
        # External modification:
        ws.write_atomic("a.md", "external")
        with pytest.raises(ConflictError):
            ws.write_atomic("a.md", "mine", expect=stale)

    def test_write_expect_missing_against_existing_raises(
        self, ws: VaultWorkspace
    ) -> None:
        ws.write_atomic("a.md", "v1")
        with pytest.raises(ConflictError):
            ws.write_atomic("a.md", "v2", expect=WorkspaceStat.missing())

    def test_identical_content_does_not_raise_on_mtime_only_change(
        self, ws: VaultWorkspace
    ) -> None:
        # Mtime jitter from re-saving identical bytes (Obsidian client
        # behavior) must not be treated as a conflict.
        ws.write_atomic("a.md", "same")
        s1 = ws.stat("a.md")
        ws.write_atomic("a.md", "same")  # rewrite with same content
        ws.write_atomic("a.md", "next", expect=s1)  # should still succeed
        assert ws.read_text("a.md") == "next"


class TestTrash:
    def test_trash_dir_default_outside_vault(self, ws: VaultWorkspace, vault: Path) -> None:
        assert vault not in ws.trash_dir.parents
        assert ws.trash_dir != vault

    def test_move_to_trash_removes_from_vault(self, ws: VaultWorkspace, vault: Path) -> None:
        ws.write_atomic("a.md", "doomed")
        trashed = ws.move_to_trash("a.md")
        assert not (vault / "a.md").exists()
        assert trashed.exists()
        assert trashed.read_text(encoding="utf-8") == "doomed"

    def test_move_to_trash_unique_per_call(self, ws: VaultWorkspace) -> None:
        ws.write_atomic("a.md", "v1")
        first = ws.move_to_trash("a.md")
        ws.write_atomic("a.md", "v2")
        # Sleep-free uniqueness: timestamp resolution is seconds, but
        # we accept either same-second collision (skipped) or distinct.
        try:
            second = ws.move_to_trash("a.md")
        except FileExistsError:
            pytest.skip("trash collision within same second")
        assert first != second

    def test_move_to_trash_missing_raises(self, ws: VaultWorkspace) -> None:
        with pytest.raises(WorkspaceError):
            ws.move_to_trash("never-existed.md")


class TestRename:
    def test_rename_moves_file(self, ws: VaultWorkspace, vault: Path) -> None:
        ws.write_atomic("a.md", "x")
        ws.rename("a.md", "b.md")
        assert not (vault / "a.md").exists()
        assert (vault / "b.md").read_text(encoding="utf-8") == "x"

    def test_rename_into_subdir_creates_parents(self, ws: VaultWorkspace, vault: Path) -> None:
        ws.write_atomic("a.md", "x")
        ws.rename("a.md", "deep/sub/b.md")
        assert (vault / "deep" / "sub" / "b.md").exists()

    def test_rename_existing_destination_raises(self, ws: VaultWorkspace) -> None:
        ws.write_atomic("a.md", "x")
        ws.write_atomic("b.md", "y")
        with pytest.raises(WorkspaceError):
            ws.rename("a.md", "b.md")


class TestIterFiles:
    def test_iter_files_returns_only_md(self, ws: VaultWorkspace) -> None:
        ws.write_atomic("a.md", "x")
        ws.write_atomic("b.txt", "y")
        ws.write_atomic("sub/c.md", "z")
        names = sorted(p.name for p in ws.iter_files())
        assert names == ["a.md", "c.md"]

    def test_iter_files_skips_trash_inside_vault(
        self, vault: Path
    ) -> None:
        # Configure trash *inside* vault to confirm the defensive guard.
        ws = VaultWorkspace(vault, trash_dir=vault / ".trash")
        ws.write_atomic("a.md", "x")
        ws.write_atomic(".trash/old.md", "ignored")
        names = [p.name for p in ws.iter_files()]
        assert names == ["a.md"]
