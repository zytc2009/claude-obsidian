"""Tests for skills.obsidian.live_note."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills.obsidian import live_note as ln
from skills.obsidian.runs import RunStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    for d in [
        "00-Inbox",
        "02-Projects",
        "03-Knowledge/Topics",
        "03-Knowledge/Concepts",
        "03-Knowledge/Literature",
        "03-Knowledge/MOCs",
    ]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _live_note(
    objective: str = "track RAG progress",
    *,
    active: bool = True,
    extra: str = "",
) -> str:
    return (
        "---\n"
        "type: topic\n"
        f"live_active: {'true' if active else 'false'}\n"
        f"live_objective: {objective}\n"
        f"{extra}"
        "---\n"
        "# 主题说明\n"
        "Tracks RAG techniques.\n"
        "# 当前结论\n"
        "Hybrid retrieval helps.\n"
    )


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


class TestParseConfig:
    def test_active_true_recognized(self) -> None:
        cfg = ln.parse_config({"live_active": "true", "live_objective": "x"})
        assert cfg.active is True
        assert cfg.objective == "x"
        assert cfg.is_runnable

    def test_inactive_when_objective_blank(self) -> None:
        cfg = ln.parse_config({"live_active": "true"})
        assert cfg.active is True
        assert not cfg.is_runnable

    def test_inactive_when_active_false(self) -> None:
        cfg = ln.parse_config({"live_active": "false", "live_objective": "x"})
        assert not cfg.is_runnable

    def test_truthy_variants(self) -> None:
        for v in ["true", "yes", "1", "on", "TRUE"]:
            assert ln.parse_config({"live_active": v}).active is True
        for v in ["false", "no", "0", "off", ""]:
            assert ln.parse_config({"live_active": v}).active is False


# ---------------------------------------------------------------------------
# update_state
# ---------------------------------------------------------------------------


class TestUpdateState:
    def test_writes_three_fields(self) -> None:
        text = "---\ntype: topic\n---\nbody"
        out = ln.update_state(
            text,
            last_run_at="2026-05-10T10:00:00",
            last_run_summary="ok",
            last_run_error="",
        )
        assert "live_last_run_at: 2026-05-10T10:00:00" in out
        assert "live_last_run_summary: ok" in out
        assert "live_last_run_error: " in out

    def test_clears_error_on_success(self) -> None:
        text = (
            "---\n"
            "type: topic\n"
            "live_last_run_error: previous failure\n"
            "---\n"
        )
        out = ln.update_state(
            text,
            last_run_at="2026-05-10T10:00:00",
            last_run_summary="recovered",
            last_run_error="",
        )
        # Field should be present but empty.
        line = next(
            (l for l in out.splitlines() if l.startswith("live_last_run_error:")),
            "",
        )
        assert line == "live_last_run_error: "


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestListLiveNotes:
    def test_finds_only_active(self, vault: Path) -> None:
        _write(vault / "03-Knowledge/Topics/Topic - Live.md", _live_note())
        _write(
            vault / "03-Knowledge/Topics/Topic - Inactive.md",
            _live_note(active=False),
        )
        _write(vault / "03-Knowledge/Concepts/Concept - X.md", "---\n---\nbody\n")
        out = ln.list_live_notes(vault)
        stems = [e.stem for e in out]
        assert stems == ["Topic - Live"]

    def test_format_empty(self) -> None:
        assert "No active Live Notes" in ln.format_list([])

    def test_format_includes_objective(self, vault: Path) -> None:
        _write(
            vault / "03-Knowledge/Topics/Topic - Live.md",
            _live_note(objective="track RAG progress"),
        )
        out = ln.format_list(ln.list_live_notes(vault))
        assert "Topic - Live" in out
        assert "track RAG progress" in out


# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------


class TestGatherContext:
    def test_collects_top_level_sections(self, vault: Path) -> None:
        path = vault / "03-Knowledge/Topics/Topic - Live.md"
        _write(path, _live_note())
        ctx = ln.gather_context(vault, path)
        assert "主题说明" in ctx.sections
        assert "当前结论" in ctx.sections
        assert ctx.config.objective == "track RAG progress"

    def test_relative_path_set(self, vault: Path) -> None:
        path = vault / "03-Knowledge/Topics/Topic - Live.md"
        _write(path, _live_note())
        ctx = ln.gather_context(vault, path)
        assert ctx.relative_path.endswith("Topic - Live.md")

    def test_to_dict_has_expected_keys(self, vault: Path) -> None:
        path = vault / "03-Knowledge/Topics/Topic - Live.md"
        _write(path, _live_note())
        ctx = ln.gather_context(vault, path)
        d = ctx.to_dict()
        for key in [
            "note_path",
            "relative_path",
            "objective",
            "sections",
            "related",
            "organize_reasons",
            "suggested_output",
            "confidence",
        ]:
            assert key in d


# ---------------------------------------------------------------------------
# run_live_note lifecycle
# ---------------------------------------------------------------------------


class TestRunLiveNoteSuccess:
    def test_emits_started_and_done_events(self, vault: Path) -> None:
        path = vault / "03-Knowledge/Topics/Topic - Live.md"
        _write(path, _live_note())
        result = ln.run_live_note(vault, "Topic - Live")
        assert result.success is True
        assert result.run_id

        run_log = vault / "runs" / f"{result.run_id}.jsonl"
        events = [
            json.loads(line)
            for line in run_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        types = [e["event_type"] for e in events]
        assert "live_note_run_started" in types
        assert "live_note_run_done" in types
        assert types[-1] == "run_done"

    def test_updates_frontmatter_state(self, vault: Path) -> None:
        path = vault / "03-Knowledge/Topics/Topic - Live.md"
        _write(path, _live_note())
        ln.run_live_note(vault, "Topic - Live")
        text = path.read_text(encoding="utf-8")
        # Updated timestamp present, error cleared.
        line_at = next(
            (l for l in text.splitlines() if l.startswith("live_last_run_at:")), ""
        )
        line_summary = next(
            (l for l in text.splitlines() if l.startswith("live_last_run_summary:")),
            "",
        )
        line_error = next(
            (l for l in text.splitlines() if l.startswith("live_last_run_error:")),
            "",
        )
        assert line_at not in {"", "live_last_run_at: "}
        assert "objective=" in line_summary
        assert line_error == "live_last_run_error: "

    def test_clears_previous_error(self, vault: Path) -> None:
        path = vault / "03-Knowledge/Topics/Topic - Live.md"
        _write(
            path,
            _live_note(extra="live_last_run_error: previous boom\n"),
        )
        ln.run_live_note(vault, "Topic - Live")
        text = path.read_text(encoding="utf-8")
        assert "live_last_run_error: previous boom" not in text


class TestRunLiveNoteFailure:
    def test_missing_note_returns_no_run(self, vault: Path) -> None:
        result = ln.run_live_note(vault, "Topic - Missing")
        assert result.success is False
        assert result.run_id == ""
        assert "not found" in result.error

    def test_inactive_marked_failed_with_run_log(self, vault: Path) -> None:
        path = vault / "03-Knowledge/Topics/Topic - Inactive.md"
        _write(path, _live_note(active=False))
        result = ln.run_live_note(vault, "Topic - Inactive")
        assert result.success is False
        assert result.run_id

        log = vault / "runs" / f"{result.run_id}.jsonl"
        events = [
            json.loads(line)
            for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        types = [e["event_type"] for e in events]
        assert "live_note_run_failed" in types
        assert types[-1] == "run_failed"

        text = path.read_text(encoding="utf-8")
        assert "live_last_run_error: not runnable" in text

    def test_missing_objective_marked_failed(self, vault: Path) -> None:
        path = vault / "03-Knowledge/Topics/Topic - NoGoal.md"
        _write(
            path,
            "---\nlive_active: true\nlive_objective: \n---\nbody\n",
        )
        result = ln.run_live_note(vault, "Topic - NoGoal")
        assert result.success is False
        assert "objective is empty" in result.error


# ---------------------------------------------------------------------------
# format_context smoke
# ---------------------------------------------------------------------------


class TestFormatContext:
    def test_includes_objective_and_sections(self, vault: Path) -> None:
        path = vault / "03-Knowledge/Topics/Topic - Live.md"
        _write(path, _live_note())
        ctx = ln.gather_context(vault, path)
        out = ln.format_context(ctx)
        assert "objective: track RAG progress" in out
        assert "# 主题说明" in out
        assert "Next" in out
        assert "cascade-update" in out
