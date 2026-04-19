from skills.obsidian.importers.base import ImportResult


class TestCaptureIntegration:
    def test_write_note_triggers_relation_extraction_when_enabled(self, tmp_path, monkeypatch):
        import skills.obsidian.obsidian_writer as ow
        from skills.obsidian.relation_extractor import append_related_concepts

        monkeypatch.setenv("OBSIDIAN_RELATION_EXTRACT", "1")
        def _fake_relation_extract(vault, path):
            append_related_concepts(path, ["[[Concept - RAG]]"])
            return ["[[Concept - RAG]]"]

        monkeypatch.setattr(ow, "relation_extract_and_link", _fake_relation_extract)
        path = ow.write_note(
            vault=tmp_path,
            note_type="literature",
            title="RAG Survey",
            fields={
                "核心观点": "Retrieval matters.",
                "方法要点": "Use retrieval.",
                "原文主要内容": "Full text.",
            },
            is_draft=False,
        )
        text = path.read_text(encoding="utf-8")
        assert "## 相关概念" in text
        assert "[[Concept - RAG]]" in text

    def test_capture_mode_writes_literature_from_import_result(self, tmp_path, monkeypatch):
        import skills.obsidian.obsidian_writer as ow

        monkeypatch.setenv("OBSIDIAN_RELATION_EXTRACT", "0")
        monkeypatch.setattr(
            ow,
            "capture_fetch_url",
            lambda url: ImportResult(
                title="微信文章标题",
                content="原文第一段\n\n原文第二段",
                summary="原文第一段",
                platform="wechat",
                source_url=url,
                metadata={"author": "Alice"},
            ),
        )
        ow.main(
            [
                "--type", "capture",
                "--url", "https://mp.weixin.qq.com/s/test",
                "--fields", '{"核心观点":"自定义观点","方法要点":"自定义方法"}',
                "--vault", str(tmp_path),
            ]
        )
        literature_dir = tmp_path / "03-Knowledge" / "Literature"
        created = list(literature_dir.glob("*.md"))
        assert created
        text = created[0].read_text(encoding="utf-8")
        assert "微信文章标题" in text
        assert "原文第一段" in text
        assert "自定义观点" in text
        assert "platform: wechat" in text
