"""Tests for skills.obsidian.templates."""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.obsidian import templates as tpl


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------


class TestRouting:
    def test_is_draft_when_majority_required_empty(self) -> None:
        assert tpl.is_draft_by_content("literature", {"核心观点": "", "方法要点": ""}) is True

    def test_is_not_draft_when_majority_filled(self) -> None:
        assert (
            tpl.is_draft_by_content(
                "literature", {"核心观点": "x", "方法要点": "y"}
            )
            is False
        )

    def test_is_not_draft_when_no_required_fields(self) -> None:
        assert tpl.is_draft_by_content("moc", {}) is False

    def test_get_target_path_inbox_for_drafts(self, tmp_path: Path) -> None:
        assert tpl.get_target_path(tmp_path, "literature", True) == tmp_path / "00-Inbox"

    def test_get_target_path_uses_note_config(self, tmp_path: Path) -> None:
        assert (
            tpl.get_target_path(tmp_path, "topic", False)
            == tmp_path / "03-Knowledge/Topics"
        )

    def test_make_filename_basic(self, tmp_path: Path) -> None:
        assert tpl.make_filename("Topic", "RAG", tmp_path) == "Topic - RAG.md"

    def test_make_filename_collision_appends_date(self, tmp_path: Path) -> None:
        existing = tmp_path / "Topic - RAG.md"
        existing.write_text("x", encoding="utf-8")
        out = tpl.make_filename("Topic", "RAG", tmp_path)
        assert out.startswith("Topic - RAG ")
        assert out.endswith(".md")
        # The collision suffix is today's date in YYYY-MM-DD form.
        assert len(out) == len("Topic - RAG YYYY-MM-DD.md")


# ---------------------------------------------------------------------------
# Frontmatter renderer
# ---------------------------------------------------------------------------


class TestFrontmatter:
    def test_active_status_for_normal_types(self) -> None:
        out = tpl.render_frontmatter("topic", {})
        assert "type: topic" in out
        assert "status: active" in out

    def test_review_status_for_article(self) -> None:
        out = tpl.render_frontmatter("article", {})
        assert "status: review" in out

    def test_draft_overrides_status(self) -> None:
        out = tpl.render_frontmatter("topic", {}, is_draft=True)
        assert "status: draft" in out

    def test_includes_platform_and_source_url_when_present(self) -> None:
        out = tpl.render_frontmatter(
            "literature",
            {"platform": "wechat", "source_url": "https://x"},
        )
        assert "platform: wechat" in out
        assert "source_url: https://x" in out

    def test_article_includes_source_notes_and_target_audience(self) -> None:
        out = tpl.render_frontmatter("article", {})
        assert "source_notes: []" in out
        assert 'target_audience: ""' in out


# ---------------------------------------------------------------------------
# Body renderers
# ---------------------------------------------------------------------------


class TestBodyRenderers:
    @pytest.mark.parametrize(
        "renderer,note_type",
        [
            (tpl.render_literature, "literature"),
            (tpl.render_concept, "concept"),
            (tpl.render_topic, "topic"),
            (tpl.render_project, "project"),
            (tpl.render_moc, "moc"),
            (tpl.render_article, "article"),
        ],
    )
    def test_renderer_emits_frontmatter(self, renderer, note_type: str) -> None:
        out = renderer("My Title", {})
        assert out.startswith("---\n")
        assert f"type: {note_type}" in out

    def test_literature_body_includes_title_and_fields(self) -> None:
        out = tpl.render_literature(
            "Attention Is All You Need",
            {"author": "Vaswani", "核心观点": "self-attention scales"},
        )
        assert "标题：Attention Is All You Need" in out
        assert "self-attention scales" in out

    def test_topic_body_includes_six_sections(self) -> None:
        out = tpl.render_topic("RAG", {})
        for section in [
            "# 主题说明",
            "# 核心问题",
            "# 重要资料",
            "# 相关项目",
            "# 当前结论",
            "# 未解决问题",
        ]:
            assert section in out

    def test_renderers_table_round_trip(self) -> None:
        for note_type, renderer in tpl.RENDERERS.items():
            assert callable(renderer)
            out = renderer("X", {})
            assert f"type: {note_type}" in out


# ---------------------------------------------------------------------------
# Daily scaffold
# ---------------------------------------------------------------------------


def test_daily_frontmatter_template_renders_with_today() -> None:
    rendered = tpl.DAILY_FRONTMATTER.format(today="2026-05-10")
    assert "type: daily" in rendered
    assert "created: 2026-05-10" in rendered
    assert "# Fleeting" in rendered
