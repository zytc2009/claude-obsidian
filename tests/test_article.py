from pathlib import Path

from skills.obsidian.obsidian_writer import (
    _check_duplicate,
    query_vault,
    render_article,
    write_note,
)
from skills.obsidian.profile_manager import upsert_profile


class TestArticleRender:
    def test_render_article_includes_required_sections(self):
        text = render_article(
            "RAG Writing",
            {
                "核心论点": "Write with explicit retrieval context.",
                "正文": "Body text.",
                "结语": "Closing.",
                "source_notes": "[[Literature - RAG Survey]]",
                "target_audience": "Engineers",
            },
        )
        assert "type: article" in text
        assert "status: review" in text
        assert "# RAG Writing" in text
        assert "## 核心论点" in text
        assert "## 正文" in text
        assert "## 结语" in text
        assert "## 来源" in text
        assert "## 目标读者" in text

    def test_render_article_uses_placeholder_for_missing_source_fields(self):
        text = render_article(
            "RAG Writing",
            {
                "核心论点": "Write with explicit retrieval context.",
                "正文": "Body text.",
                "结语": "Closing.",
            },
        )
        assert "## 来源" in text
        assert "_待补充_" in text


class TestArticleDuplicateDetection:
    def test_check_duplicate_matches_similar_titles(self, tmp_path):
        articles_dir = tmp_path / "06-Articles"
        articles_dir.mkdir(parents=True)
        existing = articles_dir / "Article - Multi Agent Systems.md"
        existing.write_text(
            "---\ntype: article\n---\n# Multi Agent Systems\n",
            encoding="utf-8",
        )
        duplicate = _check_duplicate(tmp_path, "article", "Multi-Agent Systems")
        assert duplicate == existing

    def test_write_note_reuses_existing_article(self, tmp_path):
        first = write_note(
            vault=tmp_path,
            note_type="article",
            title="RAG In Practice",
            fields={
                "核心论点": "Retrieval should be explicit.",
                "正文": "Body.",
                "结语": "Done.",
                "source_notes": "[[Literature - RAG Survey]]",
            },
            is_draft=False,
        )
        second = write_note(
            vault=tmp_path,
            note_type="article",
            title="RAG In Practice",
            fields={
                "核心论点": "Retrieval should be explicit.",
                "正文": "Updated body.",
                "结语": "Done.",
                "source_notes": "[[Literature - RAG Survey]]",
            },
            is_draft=False,
        )
        assert first == second
        assert len(list((tmp_path / "06-Articles").glob("*.md"))) == 1


class TestQueryProfileInjection:
    def test_query_returns_profile_context_when_profiles_exist(self, tmp_path):
        upsert_profile(tmp_path, "personal", "基本信息", "姓名: Alice")
        result = query_vault(tmp_path, "nothing relevant")
        assert "profile_context" in result
        assert "姓名: Alice" in result["profile_context"]
