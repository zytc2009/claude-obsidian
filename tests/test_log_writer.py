"""Tests for skills.obsidian.log_writer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills.obsidian import log_writer as lw


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# Feedback target normalization
# ---------------------------------------------------------------------------


class TestNormalizeFeedbackTarget:
    def test_strips_md_extension(self) -> None:
        assert lw.normalize_feedback_target("Topic - X.md") == "Topic - X"

    def test_passes_through_stem(self) -> None:
        assert lw.normalize_feedback_target("Topic - X") == "Topic - X"

    def test_empty_returns_empty(self) -> None:
        assert lw.normalize_feedback_target("") == ""
        assert lw.normalize_feedback_target("   ") == ""


# ---------------------------------------------------------------------------
# Operation log
# ---------------------------------------------------------------------------


class TestOperationLog:
    def test_creates_log_with_header_when_missing(self, vault: Path) -> None:
        out = lw.append_operation_log(vault, "write", "Topic - Foo")
        assert out == vault / lw.LOG_FILE
        text = out.read_text(encoding="utf-8")
        assert text.startswith("# Vault Operation Log")
        assert "write | Topic - Foo" in text

    def test_appends_subsequent_entries(self, vault: Path) -> None:
        lw.append_operation_log(vault, "write", "First")
        lw.append_operation_log(vault, "write", "Second")
        text = (vault / lw.LOG_FILE).read_text(encoding="utf-8")
        assert "First" in text and "Second" in text

    def test_includes_details(self, vault: Path) -> None:
        lw.append_operation_log(vault, "write", "X", details=["a", "b"])
        text = (vault / lw.LOG_FILE).read_text(encoding="utf-8")
        assert "- a" in text and "- b" in text


class TestSplitLogEntries:
    def test_no_entries(self) -> None:
        header, entries = lw.split_log_entries("# Header only\n")
        assert header == "# Header only"
        assert entries == []

    def test_splits_on_h2_marker(self) -> None:
        text = "# Header\n\n## [2026-05-10] write\n- a\n\n## [2026-05-10] write\n- b\n"
        header, entries = lw.split_log_entries(text)
        assert header == "# Header"
        assert len(entries) == 2
        assert entries[0].startswith("## [2026-05-10] write")
        assert "- a" in entries[0]


class TestRotation:
    def test_skips_when_under_threshold(self, vault: Path, monkeypatch) -> None:
        monkeypatch.setattr(lw, "MAX_LOG_ENTRIES", 5)
        for i in range(3):
            lw.append_operation_log(vault, "op", f"#{i}")
        # No archive expected.
        assert not (vault / lw.LOG_ARCHIVE_FILE).exists()

    def test_archives_overflow(self, vault: Path, monkeypatch) -> None:
        monkeypatch.setattr(lw, "MAX_LOG_ENTRIES", 3)
        for i in range(6):
            lw.append_operation_log(vault, "op", f"#{i}")
        archive = (vault / lw.LOG_ARCHIVE_FILE).read_text(encoding="utf-8")
        kept = (vault / lw.LOG_FILE).read_text(encoding="utf-8")
        assert "#0" in archive and "#1" in archive
        assert "#5" in kept
        assert "#0" not in kept


# ---------------------------------------------------------------------------
# JSONL streams
# ---------------------------------------------------------------------------


class TestJSONLStreams:
    def test_append_correction_events_writes_lines(self, vault: Path) -> None:
        events = [
            {"event_type": "lint_issue_detected", "note": "a.md"},
            {"event_type": "lint_issue_detected", "note": "b.md"},
        ]
        out = lw.append_correction_events(vault, events)
        assert out == vault / lw.CORRECTIONS_FILE
        lines = out.read_text(encoding="utf-8").splitlines()
        assert [json.loads(l)["note"] for l in lines] == ["a.md", "b.md"]

    def test_append_correction_events_empty_returns_none(self, vault: Path) -> None:
        assert lw.append_correction_events(vault, []) is None
        assert not (vault / lw.CORRECTIONS_FILE).exists()


class TestSuggestionFeedback:
    def test_writes_event_and_log_entry(self, vault: Path) -> None:
        out = lw.append_suggestion_feedback(
            vault,
            suggestion_type="link",
            action="reject",
            source_note="Literature - X",
            target_notes=["Topic - Y.md"],
            reason="not relevant",
        )
        assert out == vault / lw.EVENTS_FILE
        events = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
        assert events[0]["event_type"] == "suggestion_feedback"
        assert events[0]["target_notes"] == ["Topic - Y"]  # normalized
        # Operation log mirror.
        log_text = (vault / lw.LOG_FILE).read_text(encoding="utf-8")
        assert "suggestion-feedback" in log_text
        assert "not relevant" in log_text


# ---------------------------------------------------------------------------
# Side channels
# ---------------------------------------------------------------------------


class TestOrphanCorrection:
    def test_emits_when_no_topic_parent(self, vault: Path) -> None:
        note = vault / "03-Knowledge" / "Concepts" / "Concept - Foo.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("x", encoding="utf-8")
        lw.maybe_emit_orphan_correction(vault, note, suggestions=[], is_draft=False)
        events = [
            json.loads(l)
            for l in (vault / lw.CORRECTIONS_FILE).read_text(encoding="utf-8").splitlines()
        ]
        assert events[0]["issue_type"] == "orphan-on-create"

    def test_skips_drafts(self, vault: Path) -> None:
        note = vault / "03-Knowledge" / "Concepts" / "Concept - Foo.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("x", encoding="utf-8")
        lw.maybe_emit_orphan_correction(vault, note, suggestions=[], is_draft=True)
        assert not (vault / lw.CORRECTIONS_FILE).exists()

    def test_skips_when_topic_present(self, vault: Path) -> None:
        note = vault / "03-Knowledge" / "Concepts" / "Concept - Foo.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("x", encoding="utf-8")
        suggestions = [(Path("03-Knowledge/Topics/Topic - X.md"), "...")]
        lw.maybe_emit_orphan_correction(vault, note, suggestions, is_draft=False)
        assert not (vault / lw.CORRECTIONS_FILE).exists()

    def test_skips_outside_knowledge_dir(self, vault: Path) -> None:
        note = vault / "00-Inbox" / "Concept - Foo.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("x", encoding="utf-8")
        lw.maybe_emit_orphan_correction(vault, note, suggestions=[], is_draft=False)
        assert not (vault / lw.CORRECTIONS_FILE).exists()


class TestPrintFeedbackHint:
    def test_silent_when_missing_args(self, vault: Path, capsys) -> None:
        lw.print_feedback_hint("", "link", ["X"])
        assert capsys.readouterr().out == ""

    def test_emits_command_with_targets(self, vault: Path, capsys) -> None:
        lw.print_feedback_hint("Lit - X", "link", ["Topic - Y.md", "Topic - Z"])
        out = capsys.readouterr().out
        assert "[Feedback hint]" in out
        # Targets normalized to stems and joined by comma.
        assert "Topic - Y,Topic - Z" in out
