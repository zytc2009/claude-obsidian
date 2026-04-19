from pathlib import Path

import pytest

from skills.obsidian import relation_extractor as rext


class TestTruncation:
    def test_short_content_returns_as_is(self):
        text = "short content"
        assert rext.truncate_content_smart(text) == text

    def test_long_content_is_shortened(self):
        text = ("段落一\n\n" + "中间 " * 200 + "\n\n段落尾")
        truncated = rext.truncate_content_smart(text, max_tokens=50)
        assert len(truncated) < len(text)
        assert "段落一" in truncated
        assert "段落尾" in truncated


class TestJsonExtraction:
    def test_extracts_json_from_code_block(self):
        raw = "```json\n{\"concepts\":[{\"name\":\"RAG\"}]}\n```"
        assert rext._extract_json(raw) == "{\"concepts\":[{\"name\":\"RAG\"}]}"

    def test_extracts_json_with_prefix_text(self):
        raw = "好的，结果如下：{\"concepts\":[{\"name\":\"RAG\"}]}"
        assert rext._extract_json(raw).startswith("{")


class TestExtractConcepts:
    def test_returns_list(self, monkeypatch):
        monkeypatch.setattr(rext, "_call_llm", lambda *_: '{"concepts":[{"name":"RAG","type":"topic","description":"x"}]}')
        concepts = rext.extract_concepts("RAG", "content")
        assert concepts[0]["name"] == "RAG"


class TestMatchToVault:
    def test_exact_match(self, tmp_path):
        (tmp_path / "Concept - RAG.md").write_text("", encoding="utf-8")
        links = rext.match_to_vault([{"name": "Concept - RAG"}], tmp_path)
        assert links == ["[[Concept - RAG]]"]

    def test_normalized_match(self, tmp_path):
        (tmp_path / "Concept - Multi Agent Systems.md").write_text("", encoding="utf-8")
        links = rext.match_to_vault([{"name": "Multi-Agent Systems"}], tmp_path)
        assert links == ["[[Concept - Multi Agent Systems]]"]

    def test_no_match(self, tmp_path):
        assert rext.match_to_vault([{"name": "Unknown"}], tmp_path) == []


class TestAppendRelatedConcepts:
    def test_adds_new_section(self, tmp_path):
        note = tmp_path / "Literature - RAG.md"
        note.write_text("# Body\n", encoding="utf-8")
        rext.append_related_concepts(note, ["[[Concept - RAG]]"])
        text = note.read_text(encoding="utf-8")
        assert "## 相关概念" in text
        assert "[[Concept - RAG]]" in text

    def test_dedupes_existing_links(self, tmp_path):
        note = tmp_path / "Literature - RAG.md"
        note.write_text("## 相关概念\n[[Concept - RAG]]\n", encoding="utf-8")
        rext.append_related_concepts(note, ["[[Concept - RAG]]", "[[Topic - Retrieval]]"])
        text = note.read_text(encoding="utf-8")
        assert text.count("[[Concept - RAG]]") == 1
        assert "[[Topic - Retrieval]]" in text


class TestExtractAndLink:
    def test_requires_api_key(self, tmp_path, monkeypatch):
        note = tmp_path / "Literature - RAG.md"
        note.write_text("body", encoding="utf-8")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(EnvironmentError):
            rext.extract_and_link(tmp_path, note)
