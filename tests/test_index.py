"""Tests for skills.obsidian.index."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from skills.obsidian import index as idx


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    for rel, _ in idx.INDEX_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_index_entry_with_summary_and_updated(tmp_path: Path) -> None:
    note = tmp_path / "Topic - RAG.md"
    _write(
        note,
        "---\n主题说明: how retrieval augments generation\nupdated: 2026-05-10\n---\nbody",
    )
    line = idx.index_entry(note)
    assert "[[Topic - RAG]]" in line
    assert "how retrieval" in line
    assert "(2026-05-10)" in line


def test_index_entry_truncates_summary(tmp_path: Path) -> None:
    long_summary = "x" * 200
    note = tmp_path / "Topic - Foo.md"
    _write(note, f"---\n主题说明: {long_summary}\n---\n")
    line = idx.index_entry(note)
    # Summary truncated to 60 chars after the em-dash separator.
    assert " — " in line
    summary_part = line.split(" — ", 1)[1].split(" (", 1)[0]
    assert len(summary_part) <= 60


def test_rebuild_index_creates_index_md(vault: Path) -> None:
    _write(
        vault / "03-Knowledge/Topics/Topic - RAG.md",
        "---\n主题说明: about RAG\nupdated: 2026-05-10\n---\n",
    )
    _write(
        vault / "03-Knowledge/Concepts/Concept - X.md",
        "---\n一句话定义: definition\nupdated: 2026-05-09\n---\n",
    )
    out = idx.rebuild_index(vault)
    assert out == vault / idx.INDEX_FILE
    text = out.read_text(encoding="utf-8")
    assert "# Knowledge Base Index" in text
    assert "## Topics (1)" in text
    assert "## Concepts (1)" in text
    assert "[[Topic - RAG]]" in text


def test_rebuild_index_recent_section_lists_last_7_days(vault: Path) -> None:
    today = date.today().isoformat()
    eight_days_ago = (date.today() - timedelta(days=8)).isoformat()
    _write(
        vault / "03-Knowledge/Topics/Topic - Recent.md",
        f"---\nupdated: {today}\n---\n",
    )
    _write(
        vault / "03-Knowledge/Topics/Topic - Old.md",
        f"---\nupdated: {eight_days_ago}\n---\n",
    )
    text = idx.rebuild_index(vault).read_text(encoding="utf-8")
    assert "## Recent (last 7 days)" in text
    recent_section = text.split("## Recent (last 7 days)", 1)[1]
    assert "Topic - Recent" in recent_section
    assert "Topic - Old" not in recent_section


def test_append_to_index_inserts_under_section(vault: Path) -> None:
    _write(
        vault / "03-Knowledge/Topics/Topic - Existing.md",
        "---\nupdated: 2026-05-01\n---\n",
    )
    idx.rebuild_index(vault)

    new_note = vault / "03-Knowledge/Topics/Topic - Fresh.md"
    _write(new_note, "---\n主题说明: brand new\nupdated: 2026-05-10\n---\n")
    idx.append_to_index(vault, new_note, "Topics")

    text = (vault / idx.INDEX_FILE).read_text(encoding="utf-8")
    topics_block = text.split("## Topics", 1)[1].split("\n## ", 1)[0]
    assert "Topic - Fresh" in topics_block
    assert "Topic - Existing" in topics_block


def test_append_to_index_idempotent(vault: Path) -> None:
    # Use a date outside the 7-day Recent window so the note only
    # appears in the Topics section, not also in Recent.
    _write(
        vault / "03-Knowledge/Topics/Topic - Foo.md",
        "---\nupdated: 2025-01-01\n---\n",
    )
    idx.rebuild_index(vault)
    before = (vault / idx.INDEX_FILE).read_text(encoding="utf-8")
    idx.append_to_index(vault, vault / "03-Knowledge/Topics/Topic - Foo.md", "Topics")
    after = (vault / idx.INDEX_FILE).read_text(encoding="utf-8")
    # Idempotent: second append must not change the file.
    assert before == after
    assert after.count("[[Topic - Foo]]") == 1


def test_append_to_index_creates_index_when_missing(vault: Path) -> None:
    new_note = vault / "03-Knowledge/Topics/Topic - X.md"
    _write(new_note, "---\nupdated: 2026-05-10\n---\n")
    assert not (vault / idx.INDEX_FILE).exists()
    idx.append_to_index(vault, new_note, "Topics")
    assert (vault / idx.INDEX_FILE).exists()
