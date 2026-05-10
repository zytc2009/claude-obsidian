"""Tests for skills.obsidian.session_helpers.

These mirror the original obsidian_writer session-helper tests but
exercise the new module directly. SessionMemory is optional, so most
tests just verify the no-op fallback path. Functional behavior is
already covered by tests that go through obsidian_writer's re-exports.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.obsidian import session_helpers as sh


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path


class TestNoOpFallbacks:
    """When SessionMemory is unavailable everything must no-op silently."""

    def test_record_session_query_does_not_raise(self, vault: Path) -> None:
        sh.record_session_query(vault, "anything")  # smoke

    def test_record_session_note_does_not_raise(self, vault: Path) -> None:
        sh.record_session_note(vault, "note", vault / "Concept - X.md")

    def test_session_rejected_targets_returns_set(self, vault: Path) -> None:
        out = sh.session_rejected_targets(vault, "X")
        assert isinstance(out, set)

    def test_find_session_relevant_notes_returns_list(self, vault: Path) -> None:
        out = sh.find_session_relevant_notes(vault, "x")
        assert isinstance(out, list)


class TestResolveSessionNoteRefs:
    def test_resolves_explicit_md_path(self, vault: Path) -> None:
        target = vault / "03-Knowledge" / "Concepts" / "Concept - X.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("body", encoding="utf-8")
        out = sh.resolve_session_note_refs(
            vault, ["03-Knowledge/Concepts/Concept - X.md"]
        )
        assert out == [target]

    def test_resolves_stem_via_rglob(self, vault: Path) -> None:
        target = vault / "03-Knowledge" / "Topics" / "Topic - Foo.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
        out = sh.resolve_session_note_refs(vault, ["Topic - Foo"])
        assert out == [target]

    def test_skips_unknown_names(self, vault: Path) -> None:
        out = sh.resolve_session_note_refs(vault, ["nonexistent"])
        assert out == []
