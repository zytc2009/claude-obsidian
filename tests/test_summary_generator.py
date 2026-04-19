import os
import pytest
from skills.obsidian.summary_generator import strip_markdown, generate


class TestStripMarkdown:
    def test_removes_headers(self):
        assert strip_markdown("# Title\ncontent") == "Title\ncontent"

    def test_removes_bold(self):
        assert strip_markdown("**bold** text") == "bold text"

    def test_removes_images(self):
        assert strip_markdown("![alt](http://x.com/img.jpg) text") == "text"

    def test_removes_links(self):
        assert strip_markdown("[link](http://x.com) text") == "link text"

    def test_removes_code_blocks(self):
        assert "removed" not in strip_markdown("```python\nremoved\n```")

    def test_removes_inline_code(self):
        result = strip_markdown("`x` text")
        assert "x" not in result.replace("text", "")


class TestGenerate:
    def test_returns_first_meaningful_paragraph(self):
        content = "Short.\n\nThis is a longer meaningful paragraph with enough text."
        result = generate(content, use_llm=False)
        assert "longer meaningful paragraph" in result

    def test_skips_very_short_paragraphs(self):
        content = "Hi.\n\nThis is the real content with enough characters to matter."
        result = generate(content, use_llm=False)
        assert "real content" in result

    def test_truncates_to_200_chars(self):
        content = "x" * 300
        result = generate(content, use_llm=False)
        assert len(result) <= 200

    def test_strips_markdown_before_summarizing(self):
        content = "# Header\n\n**Bold** content that is meaningful enough to return."
        result = generate(content, use_llm=False)
        assert "#" not in result
        assert "**" not in result

    def test_no_llm_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        content = "Meaningful content paragraph here, long enough to qualify."
        result = generate(content, title="Test", use_llm=True)
        assert len(result) > 0
        assert "#" not in result

    def test_llm_called_when_key_present(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        import skills.obsidian.summary_generator as sg
        monkeypatch.setattr(sg, "_llm_summary", lambda content, title: "LLM summary result")
        result = generate("any content", title="Title", use_llm=True)
        assert result == "LLM summary result"
