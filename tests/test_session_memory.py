import json

from skills.obsidian.session_memory import SessionMemory, _SESSION_MEMORY_FILE


class TestSessionMemoryLoad:
    def test_starts_empty_when_persistence_disabled(self, tmp_path):
        sm = SessionMemory(tmp_path)
        data = sm.to_dict()
        assert data["active_topics"] == []
        assert data["active_notes"] == []
        assert data["recent_queries"] == []
        assert data["rejected_targets"] == {}
        assert data["open_loops"] == []

    def test_loads_existing_session_file_when_persist_enabled(self, tmp_path):
        payload = {
            "session_id": "2026-04-16T10:00:00",
            "active_topics": ["Topic - RAG"],
            "active_notes": ["Literature - RAG Survey.md"],
            "recent_queries": ["rag chunking"],
            "rejected_targets": {"Literature - RAG Survey": ["Topic - LLM.md"]},
            "open_loops": ["decide whether to create a new topic"],
            "updated_at": "2026-04-16T10:10:00",
        }
        (tmp_path / _SESSION_MEMORY_FILE).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        sm = SessionMemory(tmp_path, persist=True)
        data = sm.to_dict()
        assert data["active_topics"] == ["Topic - RAG"]
        assert data["active_notes"] == ["Literature - RAG Survey.md"]
        assert data["rejected_targets"]["Literature - RAG Survey"] == ["Topic - LLM.md"]


class TestSessionMemoryUpdates:
    def test_dedupes_topics_and_keeps_most_recent_order(self, tmp_path):
        sm = SessionMemory(tmp_path)
        sm.add_topic("Topic - RAG")
        sm.add_topic("Topic - Agents")
        sm.add_topic("Topic - RAG")
        assert sm.to_dict()["active_topics"] == ["Topic - Agents", "Topic - RAG"]

    def test_dedupes_notes_and_queries(self, tmp_path):
        sm = SessionMemory(tmp_path)
        sm.add_note("Literature - A.md")
        sm.add_note("Literature - A.md")
        sm.add_query("attention limits")
        sm.add_query("attention limits")
        data = sm.to_dict()
        assert data["active_notes"] == ["Literature - A.md"]
        assert data["recent_queries"] == ["attention limits"]

    def test_tracks_rejected_targets_per_source(self, tmp_path):
        sm = SessionMemory(tmp_path)
        sm.reject_target("Literature - Survey", "Topic - LLM.md")
        sm.reject_target("Literature - Survey", "Topic - LLM.md")
        sm.reject_target("Literature - Survey", "Topic - RAG.md")
        data = sm.to_dict()
        assert data["rejected_targets"]["Literature - Survey"] == [
            "Topic - LLM.md",
            "Topic - RAG.md",
        ]
        assert sm.is_rejected("Literature - Survey", "Topic - LLM.md") is True

    def test_adds_and_clears_open_loops(self, tmp_path):
        sm = SessionMemory(tmp_path)
        sm.add_open_loop("decide topic parent")
        sm.add_open_loop("decide topic parent")
        sm.clear_open_loop("decide topic parent")
        assert sm.to_dict()["open_loops"] == []


class TestSessionMemoryPersistence:
    def test_save_writes_json_file(self, tmp_path):
        sm = SessionMemory(tmp_path, persist=True)
        sm.add_topic("Topic - Attention")
        sm.add_note("Literature - Attention Survey.md")
        data = json.loads((tmp_path / _SESSION_MEMORY_FILE).read_text(encoding="utf-8"))
        assert data["active_topics"] == ["Topic - Attention"]
        assert data["active_notes"] == ["Literature - Attention Survey.md"]

    def test_reset_clears_state_and_rewrites_file(self, tmp_path):
        sm = SessionMemory(tmp_path, persist=True)
        sm.add_topic("Topic - Attention")
        sm.add_open_loop("decide merge target")
        sm.reset()
        data = sm.to_dict()
        assert data["active_topics"] == []
        assert data["open_loops"] == []
        saved = json.loads((tmp_path / _SESSION_MEMORY_FILE).read_text(encoding="utf-8"))
        assert saved["active_topics"] == []


class TestSessionMemoryFormatting:
    def test_format_context_returns_empty_when_no_state(self, tmp_path):
        sm = SessionMemory(tmp_path)
        assert sm.format_context() == ""

    def test_format_context_includes_major_sections(self, tmp_path):
        sm = SessionMemory(tmp_path)
        sm.add_topic("Topic - Attention")
        sm.add_note("Literature - Attention Survey.md")
        sm.add_query("attention limits")
        sm.add_open_loop("decide parent topic")
        text = sm.format_context()
        assert "<session_memory>" in text
        assert "Topic - Attention" in text
        assert "Literature - Attention Survey.md" in text
        assert "attention limits" in text
        assert "decide parent topic" in text
