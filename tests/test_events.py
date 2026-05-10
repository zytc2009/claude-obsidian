"""Tests for skills.obsidian.events."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills.obsidian import events


def test_make_event_stamps_schema_version_and_ts() -> None:
    ev = events.make_event("note_written", note="a.md")
    assert ev["schema_version"] == events.SCHEMA_VERSION
    assert ev["event_type"] == "note_written"
    assert ev["note"] == "a.md"
    assert "ts" in ev


def test_make_event_respects_explicit_ts() -> None:
    ev = events.make_event("note_written", note="a.md", ts="2026-05-10T12:00:00")
    assert ev["ts"] == "2026-05-10T12:00:00"


def test_append_writes_jsonl(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    events.append(log, events.make_event("note_written", note="x.md"))
    events.append(log, events.make_event("note_renamed", old_path="a", new_path="b"))

    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] == "note_written"
    assert json.loads(lines[1])["event_type"] == "note_renamed"


def test_append_requires_event_type(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    with pytest.raises(ValueError):
        events.append(log, {"note": "x.md"})


def test_append_stamps_missing_schema_version(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    # Caller provides a hand-built event without schema_version.
    events.append(log, {"event_type": "note_written", "note": "x.md"})
    record = json.loads(log.read_text(encoding="utf-8").strip())
    assert record["schema_version"] == events.SCHEMA_VERSION


def test_append_many_skips_empty(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    assert events.append_many(log, []) is None
    assert not log.exists()


def test_read_events_returns_legacy_with_version_zero(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    # Simulate a legacy entry written by old obsidian_writer.
    log.write_text(
        json.dumps({"event_type": "suggestion_feedback", "ts": "2026-01-01T00:00:00"})
        + "\n",
        encoding="utf-8",
    )
    out = list(events.read_events(log))
    assert len(out) == 1
    assert out[0]["schema_version"] == 0


def test_read_events_skips_corrupt_lines(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    log.write_text(
        "not-json\n"
        + json.dumps({"event_type": "note_written", "schema_version": 1}) + "\n"
        + "\n"  # blank line
        + json.dumps([1, 2, 3]) + "\n"  # not a dict
        + json.dumps({"event_type": "step_done", "schema_version": 1}) + "\n",
        encoding="utf-8",
    )
    out = list(events.read_events(log))
    types = [ev["event_type"] for ev in out]
    assert types == ["note_written", "step_done"]


def test_convenience_builders_have_expected_shape() -> None:
    assert events.note_written("x.md", "literature")["note"] == "x.md"
    assert events.note_renamed("a", "b", backlinks_updated=3)["backlinks_updated"] == 3
    issue = events.lint_issue_detected("a.md", "broken-link", "missing")
    assert issue["resolved"] is False
    assert issue["detected_by"] == "lint"


def test_step_helpers() -> None:
    s = events.step_started("rid", "fetch")
    assert s["run_id"] == "rid" and s["step"] == "fetch"
    d = events.step_done("rid", "fetch", summary="ok", count=2)
    assert d["count"] == 2 and d["summary"] == "ok"
    f = events.step_failed("rid", "fetch", error="boom")
    assert f["error"] == "boom"
    p = events.step_planned("rid", "fetch", planned_url="x")
    assert p["planned_url"] == "x"
