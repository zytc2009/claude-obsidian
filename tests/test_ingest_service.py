"""Tests for skills.obsidian.ingest_service."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from skills.obsidian import ingest_service as ing


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    for d in [
        "00-Inbox",
        "02-Projects",
        "03-Knowledge/Topics",
        "03-Knowledge/Concepts",
        "03-Knowledge/Literature",
        "03-Knowledge/MOCs",
        "06-Articles",
    ]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestNormalizeTitle:
    def test_strips_type_prefix(self) -> None:
        assert ing.normalize_title("Literature - RAG") == "rag"

    def test_strips_trailing_date(self) -> None:
        assert ing.normalize_title("Topic - X 2026-04-10") == "x"

    def test_collapses_whitespace(self) -> None:
        assert ing.normalize_title("Topic - A  B  C") == "abc"


class TestSectionDiffSummary:
    def test_no_difference(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("# Intro\nbody\n", encoding="utf-8")
        out = ing.section_diff_summary(f, "# Intro\nbody\n")
        assert out == "no section differences"

    def test_filled_from_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        f.write_text("# Intro\n\n", encoding="utf-8")
        out = ing.section_diff_summary(f, "# Intro\nadded\n")
        assert "Intro" in out and "empty" in out


# ---------------------------------------------------------------------------
# Classification + duplicate detection
# ---------------------------------------------------------------------------


class TestClassifyIngestAction:
    def test_create_new(self, vault: Path) -> None:
        action, existing, planned = ing.classify_ingest_action(
            vault, "literature", "RAG", is_draft=False
        )
        assert action == "create"
        assert existing is None
        assert planned == vault / "03-Knowledge/Literature/Literature - RAG.md"

    def test_dated_copy_on_collision(self, vault: Path) -> None:
        existing_path = vault / "03-Knowledge/Literature/Literature - RAG.md"
        existing_path.write_text("body", encoding="utf-8")
        action, existing, planned = ing.classify_ingest_action(
            vault, "literature", "RAG", is_draft=False
        )
        assert action == "create (dated copy)"
        assert existing == existing_path
        today = date.today().isoformat()
        assert planned.name == f"Literature - RAG {today}.md"

    def test_draft_targets_inbox(self, vault: Path) -> None:
        _, _, planned = ing.classify_ingest_action(
            vault, "literature", "RAG", is_draft=True
        )
        assert planned.parent == vault / "00-Inbox"


class TestCheckDuplicate:
    def test_only_for_articles(self, vault: Path) -> None:
        assert ing.check_duplicate(vault, "literature", "X") is None

    def test_finds_high_similarity_article(self, vault: Path) -> None:
        _write(
            vault / "06-Articles/Article - Deep Dive Into RAG.md", "body"
        )
        out = ing.check_duplicate(vault, "article", "Deep Dive Into RAG Notes")
        assert out is not None
        assert out.stem.startswith("Article - Deep Dive Into RAG")

    def test_returns_none_when_dissimilar(self, vault: Path) -> None:
        _write(vault / "06-Articles/Article - Topic A.md", "body")
        assert ing.check_duplicate(vault, "article", "Completely Different") is None


# ---------------------------------------------------------------------------
# Candidate finders
# ---------------------------------------------------------------------------


class TestFindMergeCandidates:
    def test_returns_empty_when_no_keywords(self, vault: Path) -> None:
        assert ing.find_merge_candidates(vault, "the and", limit=5) == []

    def test_finds_keyword_overlap(self, vault: Path) -> None:
        _write(
            vault / "03-Knowledge/Literature/Literature - RAG Pipeline.md",
            "RAG body",
        )
        out = ing.find_merge_candidates(vault, "RAG Pipeline Survey", limit=5)
        assert len(out) >= 1
        assert "RAG" in out[0].stem


class TestFindCascadeCandidates:
    def test_returns_only_topic_candidates(self, vault: Path) -> None:
        _write(
            vault / "03-Knowledge/Topics/Topic - RAG Pipeline.md",
            "# Topic\nRAG Pipeline body\n",
        )
        new_note = vault / "Literature - RAG Pipeline Survey.md"
        new_note.write_text("body", encoding="utf-8")
        out = ing.find_cascade_candidates(vault, new_note, limit=3)
        for path, _reason in out:
            assert "Topics" in path.parts


# ---------------------------------------------------------------------------
# run_ingest_sync
# ---------------------------------------------------------------------------


class TestRunIngestSync:
    def test_updates_primary_sections(self, vault: Path) -> None:
        target = vault / "03-Knowledge/Topics/Topic - RAG.md"
        _write(target, "---\n---\n# 主题说明\nold\n# 当前结论\nold\n")
        plan = {
            "primary_fields": {"主题说明": "new"},
            "source_note": "Literature - X",
        }
        summary = ing.run_ingest_sync(vault, target, plan)
        assert any("Sections updated: 主题说明" in s for s in summary["primary_updates"])
        assert "# 主题说明\nnew" in target.read_text(encoding="utf-8")

    def test_rejects_non_topic_field_in_cascade(self, vault: Path) -> None:
        target = vault / "03-Knowledge/Topics/Topic - RAG.md"
        cascade_target = vault / "03-Knowledge/Topics/Topic - Other.md"
        _write(target, "---\n---\nbody\n")
        _write(cascade_target, "---\n---\nbody\n")
        plan = {
            "primary_fields": {},
            "cascade_updates": [
                {"target": str(cascade_target), "fields": {"unknown_field": "x"}}
            ],
        }
        with pytest.raises(ValueError, match="cascade-update only supports topic fields"):
            ing.run_ingest_sync(vault, target, plan)

    def test_missing_target_raises(self, vault: Path) -> None:
        target = vault / "03-Knowledge/Topics/Topic - Missing.md"
        with pytest.raises(FileNotFoundError):
            ing.run_ingest_sync(vault, target, {"primary_fields": {}})
