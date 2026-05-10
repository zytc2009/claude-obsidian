"""Tests for skills.obsidian.linker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills.obsidian import linker
from skills.obsidian import log_writer as lw


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Stem helpers
# ---------------------------------------------------------------------------


class TestSuggestionKeywords:
    def test_strips_type_prefix_and_short_words(self) -> None:
        kws = linker.suggestion_keywords_from_stem("Literature - RAG Survey")
        # "Literature" stripped, "RAG" kept (3-uppercase rule), "Survey" kept (>=4).
        assert "RAG" in kws
        assert "Literature" not in kws
        assert "Survey" in kws

    def test_strips_trailing_date(self) -> None:
        kws = linker.suggestion_keywords_from_stem("Topic - RAG 2026-04-10")
        assert "2026" not in kws

    def test_drops_short_lowercase_words(self) -> None:
        kws = linker.suggestion_keywords_from_stem("Concept - The And")
        assert kws == []  # "The" "And" are stop words / too short


class TestTopicCandidate:
    def test_strips_type_prefix(self) -> None:
        out = linker.topic_candidate_from_stem("Literature - RAG Pipeline Survey")
        # Survey is suffix-stop; Pipeline + RAG remain.
        assert out == "RAG Pipeline"

    def test_returns_empty_when_too_short(self) -> None:
        out = linker.topic_candidate_from_stem("Concept - A B")
        assert out == ""


# ---------------------------------------------------------------------------
# Feedback adjustments
# ---------------------------------------------------------------------------


class TestFeedbackAdjustments:
    def test_returns_empty_when_no_events(self, vault: Path) -> None:
        assert linker.load_feedback_adjustments(vault, "link", "X") == {}

    def test_aggregates_reject_and_modify_accept(self, vault: Path) -> None:
        events = [
            {
                "event_type": "suggestion_feedback",
                "suggestion_type": "link",
                "source_note": "Literature - X",
                "target_notes": ["Topic - Y"],
                "action": "reject",
            },
            {
                "event_type": "suggestion_feedback",
                "suggestion_type": "link",
                "source_note": "Literature - X",
                "target_notes": ["Topic - Y"],
                "action": "modify-accept",
            },
        ]
        path = vault / lw.EVENTS_FILE
        path.write_text(
            "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
        )
        adj = linker.load_feedback_adjustments(vault, "link", "Literature - X")
        assert adj == {"Topic - Y": {"reject": 1, "modify-accept": 1}}

    def test_filters_by_suggestion_type(self, vault: Path) -> None:
        events = [
            {
                "event_type": "suggestion_feedback",
                "suggestion_type": "topic",
                "source_note": "X",
                "target_notes": ["Y"],
                "action": "reject",
            }
        ]
        (vault / lw.EVENTS_FILE).write_text(
            json.dumps(events[0]) + "\n", encoding="utf-8"
        )
        assert linker.load_feedback_adjustments(vault, "link", "X") == {}


# ---------------------------------------------------------------------------
# Suggest links
# ---------------------------------------------------------------------------


class TestSuggestLinks:
    def test_returns_empty_when_no_keywords(self, vault: Path) -> None:
        new_note = vault / "Literature - The And.md"
        new_note.write_text("body", encoding="utf-8")
        assert linker.suggest_links(vault, new_note) == []

    def test_finds_matching_topic(self, vault: Path) -> None:
        _write(
            vault / "03-Knowledge/Topics/Topic - RAG Pipeline.md",
            "# RAG\nbody mentioning Pipeline\n",
        )
        new_note = vault / "Literature - RAG Pipeline Survey.md"
        new_note.write_text("body", encoding="utf-8")
        out = linker.suggest_links(vault, new_note)
        assert len(out) >= 1
        assert any("Topic - RAG Pipeline" in str(rel) for rel, _ in out)

    def test_skips_already_linking_notes(self, vault: Path) -> None:
        _write(
            vault / "03-Knowledge/Topics/Topic - RAG Pipeline.md",
            "[[Literature - RAG Pipeline Survey]]\n",
        )
        new_note = vault / "Literature - RAG Pipeline Survey.md"
        new_note.write_text("body", encoding="utf-8")
        out = linker.suggest_links(vault, new_note)
        assert out == []

    def test_feedback_rejection_penalizes_score(self, vault: Path) -> None:
        _write(
            vault / "03-Knowledge/Topics/Topic - RAG Pipeline.md",
            "# RAG\nPipeline\n",
        )
        new_note = vault / "Literature - RAG Pipeline Survey.md"
        new_note.write_text("body", encoding="utf-8")
        # Pre-rejection: should suggest.
        before = linker.suggest_links(vault, new_note)
        assert any("Topic - RAG Pipeline" in str(rel) for rel, _ in before)

        # Record three rejections — penalty 9 should knock the score below
        # the base_score threshold.
        for _ in range(3):
            lw.append_suggestion_feedback(
                vault,
                "link",
                "reject",
                "Literature - RAG Pipeline Survey",
                ["Topic - RAG Pipeline"],
            )
        after = linker.suggest_links(vault, new_note)
        assert all("Topic - RAG Pipeline" not in str(rel) for rel, _ in after)


class TestSuggestNewTopic:
    def test_skips_topic_notes(self, vault: Path) -> None:
        new_note = vault / "03-Knowledge" / "Topics" / "Topic - X.md"
        out = linker.suggest_new_topic(new_note, [])
        assert out == ""

    def test_suggests_when_no_topic_match(self, vault: Path) -> None:
        new_note = vault / "Literature - RAG Pipeline.md"
        out = linker.suggest_new_topic(new_note, suggestions=[])
        assert "Topic - RAG Pipeline" in out

    def test_skips_when_topic_match_exists(self, vault: Path) -> None:
        new_note = vault / "Literature - RAG Pipeline.md"
        suggestions = [(Path("03-Knowledge/Topics/Topic - X.md"), "ok")]
        assert linker.suggest_new_topic(new_note, suggestions) == ""


# ---------------------------------------------------------------------------
# Topic scout helpers
# ---------------------------------------------------------------------------


class TestScoutTokenization:
    def test_split_mixed_tokens_handles_cjk_ascii_boundary(self) -> None:
        out = linker.split_mixed_tokens("RAG检索增强generation")
        # CJK↔ASCII boundary should produce separate tokens.
        assert "RAG" in out
        assert "generation" in out

    def test_normalize_token_drops_short(self) -> None:
        assert linker.normalize_token("ab") is None

    def test_normalize_token_drops_stop_words(self) -> None:
        assert linker.normalize_token("the") is None

    def test_normalize_token_drops_boilerplate(self) -> None:
        assert linker.normalize_token("核心观点") is None


class TestScoring:
    def test_jaccard_identical(self) -> None:
        a = {"x": 3, "y": 1}
        assert linker.jaccard(a, a) == 1.0

    def test_jaccard_disjoint(self) -> None:
        assert linker.jaccard({"x": 3}, {"y": 3}) == 0.0

    def test_stem_jaccard_uses_only_high_weight(self) -> None:
        a = {"shared": 3, "low": 1}
        b = {"shared": 3, "other": 1}
        # Only "shared" has weight >= 3 in both.
        assert linker.stem_jaccard(a, b) == 1.0


class TestClustering:
    def test_singleton_cluster(self) -> None:
        notes = [(Path("a.md"), {"foo": 3})]
        clusters = linker.cluster_notes(notes)
        assert clusters == [[(Path("a.md"), {"foo": 3})]]

    def test_two_notes_with_overlap_cluster_together(self) -> None:
        a = (Path("a.md"), {"shared": 3, "x": 1})
        b = (Path("b.md"), {"shared": 3, "y": 1})
        clusters = linker.cluster_notes([a, b])
        assert len(clusters) == 1
        assert len(clusters[0]) == 2


class TestScoutTopics:
    def test_no_orphans_prints_clean_message(self, vault: Path, capsys) -> None:
        # All notes already parented under a Topic.
        _write(
            vault / "03-Knowledge/Topics/Topic - X.md",
            "[[Concept - Foo]]\n",
        )
        _write(vault / "03-Knowledge/Concepts/Concept - Foo.md", "body")
        linker.scout_topics(vault)
        out = capsys.readouterr().out
        assert "all notes have a topic parent" in out

    def test_finds_orphan_singleton(self, vault: Path, capsys) -> None:
        _write(vault / "03-Knowledge/Concepts/Concept - Lonely Token.md", "body")
        linker.scout_topics(vault)
        out = capsys.readouterr().out
        assert "Singletons" in out
        assert "Concept - Lonely Token" in out
