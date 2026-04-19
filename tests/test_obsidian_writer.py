import json
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from skills.obsidian.session_memory import _SESSION_MEMORY_FILE

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "obsidian" / "obsidian_writer.py"

from skills.obsidian.obsidian_writer import (
    NOTE_CONFIG,
    _CORRECTIONS_FILE,
    _EVENTS_FILE,
    _INDEX_FILE,
    _LOG_ARCHIVE_FILE,
    _LOG_FILE,
    _MAX_LOG_ENTRIES,
    _append_to_index,
    _classify_ingest_action,
    _extract_wikilinks,
    _parse_frontmatter,
    _section_diff_summary,
    _suggestion_keywords_from_stem,
    add_conflict_annotation,
    append_suggestion_feedback,
    add_source_reference,
    add_supporting_note,
    append_operation_log,
    append_fleeting,
    find_cascade_candidates,
    find_merge_candidates,
    get_target_path,
    is_draft_by_content,
    lint_vault,
    make_filename,
    rebuild_index,
    render_concept,
    render_literature,
    render_project,
    render_topic,
    run_ingest_sync,
    _topic_candidate_from_stem,
    find_session_relevant_notes,
    organize_vault,
    query_vault,
    record_session_query,
    suggest_links,
    suggest_new_topic,
    touch_updated,
    update_note_sections,
    write_note,
)
from skills.obsidian.profile_manager import upsert_profile


class TestIsDraftByContent:
    def test_returns_true_when_all_required_empty(self):
        fields = {"核心观点": "", "方法要点": ""}
        assert is_draft_by_content("literature", fields) is True

    def test_returns_true_when_majority_empty(self):
        # concept has 2 required fields; 2 empty = 100% → majority
        fields = {"一句话定义": "", "核心机制": ""}
        assert is_draft_by_content("concept", fields) is True

    def test_returns_false_when_majority_filled(self):
        fields = {"核心观点": "content", "方法要点": "detail"}
        assert is_draft_by_content("literature", fields) is False

    def test_returns_false_when_exactly_half_empty(self):
        # 2 required, 1 empty → 50% → NOT majority (needs > 50%)
        fields = {"核心观点": "content", "方法要点": ""}
        assert is_draft_by_content("literature", fields) is False

    def test_returns_false_for_type_with_no_required(self):
        assert is_draft_by_content("moc", {}) is False


class TestGetTargetPath:
    def test_returns_inbox_when_draft(self):
        vault = Path("/vault")
        result = get_target_path(vault, "literature", is_draft=True)
        assert result == Path("/vault/00-Inbox")

    def test_returns_literature_target_when_not_draft(self):
        vault = Path("/vault")
        result = get_target_path(vault, "literature", is_draft=False)
        assert result == Path("/vault/03-Knowledge/Literature")

    def test_returns_concept_target(self):
        vault = Path("/vault")
        result = get_target_path(vault, "concept", is_draft=False)
        assert result == Path("/vault/03-Knowledge/Concepts")

    def test_returns_topic_target(self):
        vault = Path("/vault")
        result = get_target_path(vault, "topic", is_draft=False)
        assert result == Path("/vault/03-Knowledge/Topics")

    def test_returns_project_target(self):
        vault = Path("/vault")
        result = get_target_path(vault, "project", is_draft=False)
        assert result == Path("/vault/02-Projects")

    def test_returns_moc_target(self):
        vault = Path("/vault")
        result = get_target_path(vault, "moc", is_draft=False)
        assert result == Path("/vault/03-Knowledge/MOCs")


class TestMakeFilename:
    def test_returns_simple_name_when_no_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            result = make_filename("Literature", "Test Note", target)
            assert result == "Literature - Test Note.md"

    def test_appends_date_suffix_on_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "Literature - Test Note.md").touch()
            today = date.today().strftime("%Y-%m-%d")
            result = make_filename("Literature", "Test Note", target)
            assert result == f"Literature - Test Note {today}.md"


class TestRenderLiterature:
    def test_includes_title_in_output(self):
        result = render_literature("Attention Is All You Need", {})
        assert "Attention Is All You Need" in result

    def test_fills_provided_field(self):
        fields = {"核心观点": "transformer architecture"}
        result = render_literature("Test", fields)
        assert "transformer architecture" in result

    def test_empty_field_is_blank(self):
        result = render_literature("Test", {})
        assert "_待补充_" not in result

    def test_frontmatter_type_is_literature(self):
        result = render_literature("Test", {})
        assert "type: literature" in result

    def test_frontmatter_status_active_when_not_draft(self):
        result = render_literature("Test", {}, is_draft=False)
        assert "status: active" in result

    def test_frontmatter_status_draft_when_draft(self):
        result = render_literature("Test", {}, is_draft=True)
        assert "status: draft" in result

    def test_frontmatter_includes_today_date(self):
        result = render_literature("Test", {})
        today = date.today().strftime("%Y-%m-%d")
        assert f"created: {today}" in result

    def test_source_appears_in_output(self):
        fields = {"source": "https://arxiv.org/abs/1706.03762"}
        result = render_literature("Test", fields)
        assert "https://arxiv.org/abs/1706.03762" in result


class TestRenderConcept:
    def test_includes_title_in_output(self):
        result = render_concept("Transformer", {})
        assert "Transformer" in result

    def test_fills_provided_field(self):
        fields = {"一句话定义": "基于自注意力机制的序列转换架构"}
        result = render_concept("Transformer", fields)
        assert "基于自注意力机制的序列转换架构" in result

    def test_empty_field_is_blank(self):
        result = render_concept("Test", {})
        assert "_待补充_" not in result

    def test_frontmatter_type_is_concept(self):
        result = render_concept("Test", {})
        assert "type: concept" in result

    def test_frontmatter_status_active_when_not_draft(self):
        result = render_concept("Test", {}, is_draft=False)
        assert "status: active" in result

    def test_frontmatter_includes_today_date(self):
        result = render_concept("Test", {})
        today = date.today().strftime("%Y-%m-%d")
        assert f"created: {today}" in result


class TestRenderTopic:
    def test_includes_title_in_output(self):
        result = render_topic("RAG", {})
        assert "RAG" in result

    def test_fills_provided_field(self):
        fields = {"主题说明": "Retrieval Augmented Generation overview"}
        result = render_topic("RAG", fields)
        assert "Retrieval Augmented Generation overview" in result

    def test_fills_core_question_field(self):
        fields = {"核心问题": "What retrieval settings affect answer quality?"}
        result = render_topic("RAG", fields)
        assert "What retrieval settings affect answer quality?" in result

    def test_empty_field_is_blank(self):
        result = render_topic("Test", {})
        assert "_待补充_" not in result

    def test_frontmatter_type_is_topic(self):
        result = render_topic("Test", {})
        assert "type: topic" in result


class TestRenderProject:
    def test_includes_title_in_output(self):
        result = render_project("本地知识库搭建", {})
        assert "本地知识库搭建" in result

    def test_fills_provided_field(self):
        fields = {"项目描述": "Build local RAG demo"}
        result = render_project("Test", fields)
        assert "Build local RAG demo" in result

    def test_empty_field_is_blank(self):
        result = render_project("Test", {})
        assert "_待补充_" not in result

    def test_frontmatter_type_is_project(self):
        result = render_project("Test", {})
        assert "type: project" in result

    def test_includes_solution_section(self):
        result = render_project("Test", {})
        assert "解决方案" in result


class TestAppendFleeting:
    def test_creates_daily_note_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            path = append_fleeting(vault, "测试闪念内容")
            assert path.exists()
            today = date.today().strftime("%Y-%m-%d")
            assert path.name == f"{today}.md"

    def test_content_appears_in_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            append_fleeting(vault, "一个重要的想法")
            daily_dir = vault / "01-DailyNotes"
            today = date.today().strftime("%Y-%m-%d")
            text = (daily_dir / f"{today}.md").read_text(encoding="utf-8")
            assert "一个重要的想法" in text

    def test_tags_appear_in_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            append_fleeting(vault, "想法内容", tags="#ai #test")
            daily_dir = vault / "01-DailyNotes"
            today = date.today().strftime("%Y-%m-%d")
            text = (daily_dir / f"{today}.md").read_text(encoding="utf-8")
            assert "#ai #test" in text

    def test_appends_to_existing_daily_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            daily_dir = vault / "01-DailyNotes"
            daily_dir.mkdir()
            today = date.today().strftime("%Y-%m-%d")
            filepath = daily_dir / f"{today}.md"
            filepath.write_text("---\ntype: daily\n---\n\n# Fleeting\n- 旧条目\n", encoding="utf-8")
            append_fleeting(vault, "新条目")
            text = filepath.read_text(encoding="utf-8")
            assert "旧条目" in text
            assert "新条目" in text

    def test_creates_fleeting_section_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            daily_dir = vault / "01-DailyNotes"
            daily_dir.mkdir()
            today = date.today().strftime("%Y-%m-%d")
            filepath = daily_dir / f"{today}.md"
            filepath.write_text("---\ntype: daily\n---\n\n# 今日目标\n", encoding="utf-8")
            append_fleeting(vault, "新想法")
            text = filepath.read_text(encoding="utf-8")
            assert "# Fleeting" in text
            assert "新想法" in text

    def test_timestamps_item_with_hhmm(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            append_fleeting(vault, "时间戳测试")
            daily_dir = vault / "01-DailyNotes"
            today = date.today().strftime("%Y-%m-%d")
            text = (daily_dir / f"{today}.md").read_text(encoding="utf-8")
            now_hour = datetime.now().strftime("%H:")
            assert now_hour in text


class TestWriteNote:
    def test_writes_file_to_target_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            fields = {"核心观点": "test insight", "方法要点": "test method"}
            path = write_note(
                vault=vault,
                note_type="literature",
                title="Test Paper",
                fields=fields,
                is_draft=False,
            )
            assert path.exists()
            assert path.name == "Literature - Test Paper.md"
            assert "test insight" in path.read_text(encoding="utf-8")

    def test_writes_draft_to_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            path = write_note(
                vault=vault,
                note_type="literature",
                title="Draft Paper",
                fields={},
                is_draft=True,
            )
            assert "00-Inbox" in str(path)

    def test_draft_file_has_draft_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            path = write_note(vault=vault, note_type="literature",
                              title="Draft", fields={}, is_draft=True)
            assert "status: draft" in path.read_text(encoding="utf-8")

    def test_non_draft_file_has_active_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            path = write_note(vault=vault, note_type="topic",
                              title="RAG", fields={"主题说明": "x", "当前结论": "y"},
                              is_draft=False)
            assert "status: active" in path.read_text(encoding="utf-8")

    def test_creates_target_directory_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            path = write_note(
                vault=vault,
                note_type="topic",
                title="RAG",
                fields={"主题说明": "overview"},
                is_draft=False,
            )
            assert path.exists()

    def test_writes_concept_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            path = write_note(vault=vault, note_type="concept",
                              title="Transformer",
                              fields={"一句话定义": "自注意力架构"},
                              is_draft=False)
            assert path.exists()
            assert "Concept - Transformer.md" == path.name
            assert "自注意力架构" in path.read_text(encoding="utf-8")

    def test_non_draft_write_appends_operation_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            write_note(
                vault=vault,
                note_type="literature",
                title="Logged Paper",
                fields={"核心观点": "x", "方法要点": "y"},
                is_draft=False,
            )
            text = (vault / _LOG_FILE).read_text(encoding="utf-8")
            assert "write | Literature - Logged Paper" in text
            assert "Action: created" in text

    def test_write_note_updates_session_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            write_note(
                vault=vault,
                note_type="topic",
                title="Attention Mechanism",
                fields={"主题说明": "x", "当前结论": "y"},
                is_draft=False,
            )
            data = json.loads((vault / _SESSION_MEMORY_FILE).read_text(encoding="utf-8"))
            assert "Topic - Attention Mechanism.md" in data["active_notes"]
            assert "Topic - Attention Mechanism" in data["active_topics"]


class TestSessionReadPathHelpers:
    def test_record_session_query_updates_session_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            record_session_query(vault, "attention limits")
            data = json.loads((vault / _SESSION_MEMORY_FILE).read_text(encoding="utf-8"))
            assert data["recent_queries"] == ["attention limits"]

    def test_find_session_relevant_notes_prefers_active_topics(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            topic_dir = vault / "03-Knowledge/Topics"
            lit_dir = vault / "03-Knowledge/Literature"
            topic_dir.mkdir(parents=True, exist_ok=True)
            lit_dir.mkdir(parents=True, exist_ok=True)
            note = lit_dir / "Literature - Attention Survey.md"
            note.write_text("---\ntype: literature\n---\n# 核心观点\ny\n", encoding="utf-8")
            topic_path = write_note(
                vault=vault,
                note_type="topic",
                title="Attention Mechanism",
                fields={"主题说明": "x", "当前结论": "y"},
                is_draft=False,
            )
            # re-add literature note into session state after topic creation
            from skills.obsidian.session_memory import SessionMemory
            SessionMemory(vault, persist=True).add_note("Literature - Attention Survey.md")
            results = find_session_relevant_notes(vault, "attention")
            assert results
            assert results[0].name == topic_path.name

    def test_find_session_relevant_notes_uses_query_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            topic_dir = vault / "03-Knowledge/Topics"
            lit_dir = vault / "03-Knowledge/Literature"
            topic_dir.mkdir(parents=True, exist_ok=True)
            lit_dir.mkdir(parents=True, exist_ok=True)
            topic = topic_dir / "Topic - KV Cache.md"
            note = lit_dir / "Literature - Attention Survey.md"
            topic.write_text("---\ntype: topic\n---\n# 当前结论\nx\n", encoding="utf-8")
            note.write_text("---\ntype: literature\n---\n# 核心观点\ny\n", encoding="utf-8")
            from skills.obsidian.session_memory import SessionMemory
            sm = SessionMemory(vault, persist=True)
            sm.add_topic("Topic - KV Cache")
            sm.add_note("Literature - Attention Survey.md")
            results = find_session_relevant_notes(vault, "attention")
            assert results
            assert results[0].name == "Literature - Attention Survey.md"


class TestQueryVault:
    def test_tier1_returns_topic_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            topic_dir = vault / "03-Knowledge/Topics"
            topic_dir.mkdir(parents=True, exist_ok=True)
            topic = topic_dir / "Topic - RAG.md"
            topic.write_text(
                "---\ntype: topic\n---\n"
                "# 主题说明\nRAG overview\n\n"
                "# 当前结论\nDense retrieval reduces hallucination\n\n"
                "# 未解决问题\nHow to rank long context chunks?\n",
                encoding="utf-8",
            )
            result = query_vault(vault, "rag hallucination")
            assert len(result["tier1_topics"]) == 1
            assert result["tier1_topics"][0]["title"] == "Topic - RAG"
            assert "Dense retrieval" in result["tier1_topics"][0]["当前结论"]
            assert result["tier2_grouped"] == []
            assert result["profile_context"] == ""

    def test_tier1_includes_profile_context_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            topic_dir = vault / "03-Knowledge/Topics"
            profile_dir = vault / "05-Profile"
            topic_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.mkdir(parents=True, exist_ok=True)
            topic = topic_dir / "Topic - RAG.md"
            topic.write_text(
                "---\ntype: topic\n---\n"
                "# 主题说明\nRAG overview\n\n"
                "# 当前结论\nDense retrieval reduces hallucination\n",
                encoding="utf-8",
            )
            profile = profile_dir / "Profile - Preferences.md"
            profile.write_text(
                "---\ntype: profile\nsubtype: preferences\nupdated: 2026-04-19\nversion: 1\n---\n"
                "# Preferences\n\n"
                "## 写作风格偏好\n- keep answers concise\n",
                encoding="utf-8",
            )
            result = query_vault(vault, "rag hallucination")
            assert "keep answers concise" in result["profile_context"]

    def test_tier1_uses_profile_topics_for_keyword_expansion(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            topic_dir = vault / "03-Knowledge/Topics"
            topic_dir.mkdir(parents=True, exist_ok=True)
            topic = topic_dir / "Topic - RAG.md"
            topic.write_text(
                "---\ntype: topic\n---\n"
                "# 主题说明\nRAG overview\n\n"
                "# 当前结论\nDense retrieval reduces hallucination\n",
                encoding="utf-8",
            )
            upsert_profile(
                vault,
                "projects",
                "常讨论话题",
                "- RAG\n- retrieval",
            )
            result = query_vault(vault, "what am I working on")
            assert result["tier1_topics"]
            assert result["tier1_topics"][0]["title"] == "Topic - RAG"

    def test_include_details_groups_notes_under_topic_and_keeps_orphans(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            topic_dir = vault / "03-Knowledge/Topics"
            lit_dir = vault / "03-Knowledge/Literature"
            topic_dir.mkdir(parents=True, exist_ok=True)
            lit_dir.mkdir(parents=True, exist_ok=True)
            topic = topic_dir / "Topic - Attention Mechanism.md"
            linked = lit_dir / "Literature - Attention Survey.md"
            orphan = lit_dir / "Literature - Attention Benchmark.md"
            topic.write_text(
                "---\ntype: topic\n---\n"
                "# 主题说明\nAttention overview\n\n"
                "# 当前结论\nAttention remains the core sequence primitive\n",
                encoding="utf-8",
            )
            linked.write_text(
                "---\ntype: literature\n---\n"
                "# 核心观点\nAttention improves sequence modeling\n\n"
                "# 知识连接\n[[Topic - Attention Mechanism]]\n",
                encoding="utf-8",
            )
            orphan.write_text(
                "---\ntype: literature\n---\n"
                "# 核心观点\nAttention benchmark highlights latency tradeoffs\n",
                encoding="utf-8",
            )
            result = query_vault(vault, "attention", include_details=True)
            assert result["tier1_topics"][0]["title"] == "Topic - Attention Mechanism"
            assert result["tier2_grouped"][0]["topic"] == "Topic - Attention Mechanism"
            assert result["tier2_grouped"][0]["notes"][0]["title"] == "Literature - Attention Survey"
            orphan_titles = [item["title"] for item in result["orphans"]]
            assert "Literature - Attention Benchmark" in orphan_titles

    def test_query_top1_topic_is_stable_after_related_source_ingest(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            topic_dir = vault / "03-Knowledge/Topics"
            lit_dir = vault / "03-Knowledge/Literature"
            topic_dir.mkdir(parents=True, exist_ok=True)
            lit_dir.mkdir(parents=True, exist_ok=True)
            topic = topic_dir / "Topic - RAG.md"
            topic.write_text(
                "---\ntype: topic\n---\n"
                "# 主题说明\nRAG overview\n\n"
                "# 当前结论\nDense retrieval improves grounding\n",
                encoding="utf-8",
            )
            first = query_vault(vault, "rag grounding")
            assert first["tier1_topics"][0]["title"] == "Topic - RAG"

            related = lit_dir / "Literature - RAG Systems Survey.md"
            related.write_text(
                "---\ntype: literature\n---\n"
                "# 核心观点\nRAG improves factuality and grounding\n\n"
                "# 知识连接\n[[Topic - RAG]]\n",
                encoding="utf-8",
            )
            second = query_vault(vault, "rag grounding", include_details=True)
            assert second["tier1_topics"][0]["title"] == "Topic - RAG"
            assert second["tier2_grouped"][0]["topic"] == "Topic - RAG"


class TestOrganizeVault:
    def test_returns_session_hits_and_related_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            topic_dir = vault / "03-Knowledge/Topics"
            lit_dir = vault / "03-Knowledge/Literature"
            inbox_dir = vault / "00-Inbox"
            topic_dir.mkdir(parents=True, exist_ok=True)
            lit_dir.mkdir(parents=True, exist_ok=True)
            inbox_dir.mkdir(parents=True, exist_ok=True)
            topic = topic_dir / "Topic - Attention Mechanism.md"
            lit = lit_dir / "Literature - Attention Survey.md"
            inbox = inbox_dir / "Literature - Attention Draft.md"
            topic.write_text("---\ntype: topic\n---\n# 当前结论\nattention summary\n", encoding="utf-8")
            lit.write_text("---\ntype: literature\n---\n# 核心观点\nattention details\n", encoding="utf-8")
            inbox.write_text("---\ntype: literature\nstatus: draft\n---\n# 核心观点\nattention draft\n", encoding="utf-8")
            write_note(
                vault=vault,
                note_type="topic",
                title="Attention Mechanism",
                fields={"主题说明": "x", "当前结论": "y"},
                is_draft=False,
            )
            result = organize_vault(vault, "attention")
            assert result["session_hits"]
            titles = [item["title"] for item in result["matches"]]
            assert "Literature - Attention Survey" in titles
            assert "Literature - Attention Draft" in titles
            assert result["suggested_output"] == "topic"
            assert result["confidence"] in {"medium", "high"}
            assert result["reasons"]

    def test_returns_moc_when_only_shallow_single_match_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            lit_dir = vault / "03-Knowledge/Literature"
            lit_dir.mkdir(parents=True, exist_ok=True)
            lit = lit_dir / "Literature - Bitrate Survey.md"
            lit.write_text("---\ntype: literature\n---\n# 核心观点\nbitrate tradeoffs\n", encoding="utf-8")
            result = organize_vault(vault, "bitrate")
            assert result["suggested_output"] == "moc"
            assert result["confidence"] in {"medium", "high"}
            assert any("shallow cluster" in reason or "no strong topic-level" in reason for reason in result["reasons"])

    def test_orphan_reduction_after_topic_convergence(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            topic_dir = vault / "03-Knowledge/Topics"
            lit_dir = vault / "03-Knowledge/Literature"
            topic_dir.mkdir(parents=True, exist_ok=True)
            lit_dir.mkdir(parents=True, exist_ok=True)
            note_a = lit_dir / "Literature - Attention Survey.md"
            note_b = lit_dir / "Literature - Attention Systems.md"
            note_a.write_text(
                "---\ntype: literature\nstatus: active\ncreated: 2026-04-01\nupdated: 2026-04-01\n---\n"
                "# 核心观点\nattention overview\n",
                encoding="utf-8",
            )
            note_b.write_text(
                "---\ntype: literature\nstatus: active\ncreated: 2026-04-01\nupdated: 2026-04-01\n---\n"
                "# 核心观点\nattention systems\n",
                encoding="utf-8",
            )

            before = organize_vault(vault, "attention")
            before_orphans = sum(
                1 for item in before["matches"]
                if item["type"] in {"literature", "concept", "project"} and not item["parent_topics"]
            )
            assert before_orphans == 2
            assert before["suggested_output"] == "topic"

            write_note(
                vault=vault,
                note_type="topic",
                title="Attention Mechanism",
                fields={
                    "主题说明": "attention overview",
                    "当前结论": "attention remains central",
                    "重要资料": "[[Literature - Attention Survey]]\n[[Literature - Attention Systems]]",
                },
                is_draft=False,
            )

            note_a.write_text(
                note_a.read_text(encoding="utf-8") + "\n# 知识连接\n[[Topic - Attention Mechanism]]\n",
                encoding="utf-8",
            )
            note_b.write_text(
                note_b.read_text(encoding="utf-8") + "\n# 知识连接\n[[Topic - Attention Mechanism]]\n",
                encoding="utf-8",
            )

            after = organize_vault(vault, "attention")
            after_orphans = sum(
                1 for item in after["matches"]
                if item["type"] in {"literature", "concept", "project"} and not item["parent_topics"]
            )
            assert after_orphans == 0
            assert after["confidence"] in {"medium", "high"}
            assert any("existing topic match" in reason for reason in after["reasons"])

    def test_organize_includes_profile_context_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            lit_dir = vault / "03-Knowledge/Literature"
            profile_dir = vault / "05-Profile"
            lit_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.mkdir(parents=True, exist_ok=True)
            note = lit_dir / "Literature - Attention Survey.md"
            note.write_text(
                "---\ntype: literature\n---\n# 镓稿绩瑙傜偣\nattention details\n",
                encoding="utf-8",
            )
            profile = profile_dir / "Profile - Preferences.md"
            profile.write_text(
                "---\ntype: profile\nsubtype: preferences\nupdated: 2026-04-19\nversion: 1\n---\n"
                "# Preferences\n\n"
                "## 写作风格偏好\n- keep answers concise\n",
                encoding="utf-8",
            )
            result = organize_vault(vault, "attention")
            assert "profile_context" in result
            assert "keep answers concise" in result["profile_context"]

    def test_organize_uses_profile_topics_for_keyword_expansion(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            topic_dir = vault / "03-Knowledge/Topics"
            topic_dir.mkdir(parents=True, exist_ok=True)
            topic = topic_dir / "Topic - RAG.md"
            topic.write_text(
                "---\ntype: topic\n---\n"
                "# 主题说明\nRAG overview\n\n"
                "# 当前结论\nDense retrieval reduces hallucination\n",
                encoding="utf-8",
            )
            upsert_profile(
                vault,
                "projects",
                "常讨论话题",
                "- RAG\n- retrieval",
            )
            result = organize_vault(vault, "what am I working on")
            assert result["matches"]
            assert result["matches"][0]["title"] == "Topic - RAG"


class TestParseFrontmatter:
    def test_extracts_basic_fields(self):
        text = "---\ntype: literature\nstatus: active\n---\n# body"
        fm = _parse_frontmatter(text)
        assert fm["type"] == "literature"
        assert fm["status"] == "active"

    def test_returns_empty_when_no_frontmatter(self):
        assert _parse_frontmatter("# just a heading") == {}

    def test_returns_empty_when_unclosed(self):
        assert _parse_frontmatter("---\ntype: foo\n") == {}


class TestOperationLog:
    def test_append_operation_log_creates_file_and_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            log_path = append_operation_log(
                vault, "write", "Literature - Test", ["Action: created"]
            )
            assert log_path == vault / _LOG_FILE
            text = log_path.read_text(encoding="utf-8")
            assert "# Vault Operation Log" in text
            assert "write | Literature - Test" in text
            assert "Action: created" in text

    def test_rotates_entries_after_500_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            for i in range(_MAX_LOG_ENTRIES + 1):
                append_operation_log(vault, "write", f"Entry {i}", [f"Index: {i}"])

            log_text = (vault / _LOG_FILE).read_text(encoding="utf-8")
            archive_text = (vault / _LOG_ARCHIVE_FILE).read_text(encoding="utf-8")

            assert "Entry 0" not in log_text
            assert "Entry 1" in log_text
            assert "Entry 500" in log_text
            assert "Entry 0" in archive_text
            assert "# Vault Operation Log Archive" in archive_text


class TestSuggestionFeedback:
    def test_append_suggestion_feedback_writes_jsonl_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            events_path = append_suggestion_feedback(
                vault,
                suggestion_type="link",
                action="reject",
                source_note="Literature - Attention Survey",
                target_notes=["Topic - Attention", "MOC - Transformers"],
                reason="too broad",
            )

            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            assert events[0]["event_type"] == "suggestion_feedback"
            assert events[0]["suggestion_type"] == "link"
            assert events[0]["action"] == "reject"
            assert events[0]["target_notes"] == ["Topic - Attention", "MOC - Transformers"]
            assert events[0]["reason"] == "too broad"

            log_text = (vault / _LOG_FILE).read_text(encoding="utf-8")
            assert "suggestion-feedback | Literature - Attention Survey" in log_text
            assert "Suggestion type: link" in log_text
            assert "Action: reject" in log_text

    def test_append_suggestion_feedback_normalizes_path_targets_to_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            events_path = append_suggestion_feedback(
                vault,
                suggestion_type="link",
                action="reject",
                source_note="Literature - Attention Survey",
                target_notes=["03-Knowledge/Topics/Topic - Attention.md"],
            )

            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            assert events[0]["target_notes"] == ["Topic - Attention"]

    def test_append_suggestion_feedback_updates_session_rejections(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            append_suggestion_feedback(
                vault,
                suggestion_type="link",
                action="reject",
                source_note="Literature - Attention Survey",
                target_notes=["03-Knowledge/Topics/Topic - Attention.md"],
                reason="too broad",
            )
            data = json.loads((vault / _SESSION_MEMORY_FILE).read_text(encoding="utf-8"))
            assert data["rejected_targets"]["Literature - Attention Survey"] == ["Topic - Attention"]


class TestSupportingSections:
    def test_add_supporting_note_creates_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Topic - RAG.md"
            path.write_text("---\ntype: topic\n---\n# RAG\n", encoding="utf-8")
            changed = add_supporting_note(path, "Literature - RAG Survey")
            text = path.read_text(encoding="utf-8")
            assert changed is True
            assert "# Supporting notes" in text
            assert "[[Literature - RAG Survey]]" in text

    def test_add_source_reference_creates_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Literature - RAG.md"
            path.write_text("---\ntype: literature\n---\n# RAG\n", encoding="utf-8")
            changed = add_source_reference(path, "Anthropic, 2026-04-13")
            text = path.read_text(encoding="utf-8")
            assert changed is True
            assert "# Sources" in text
            assert "Anthropic, 2026-04-13" in text

    def test_add_conflict_annotation_creates_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Topic - Attention.md"
            path.write_text("---\ntype: topic\n---\n# Attention\n", encoding="utf-8")
            changed = add_conflict_annotation(
                path,
                "Literature - New Benchmark",
                "Small-sequence inference no longer favors FlashAttention.",
                "[[Literature - FlashAttention Survey]]",
            )
            text = path.read_text(encoding="utf-8")
            assert changed is True
            assert "# Conflicts" in text
            assert "Source: [[Literature - New Benchmark]]" in text
            assert "Conflicts with: [[Literature - FlashAttention Survey]]" in text


class TestUpdateNoteSections:
    def test_replaces_existing_section_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Literature - Test.md"
            path.write_text(
                "---\ntype: literature\n---\n# 核心观点\nold text\n\n# 方法要点\nold method\n",
                encoding="utf-8",
            )
            changed = update_note_sections(path, {"核心观点": "new text"})
            text = path.read_text(encoding="utf-8")
            assert changed == ["核心观点"]
            assert "# 核心观点\nnew text" in text
            assert "old text" not in text

    def test_appends_missing_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Topic - Test.md"
            path.write_text("---\ntype: topic\n---\n# Topic\n", encoding="utf-8")
            changed = update_note_sections(path, {"当前结论": "updated conclusion"})
            text = path.read_text(encoding="utf-8")
            assert changed == ["当前结论"]
            assert "# 当前结论" in text
            assert "updated conclusion" in text


class TestTouchUpdated:
    def test_refreshes_updated_frontmatter_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Topic - Test.md"
            path.write_text(
                "---\ntype: topic\nupdated: 2026-01-01\n---\n# Topic\n",
                encoding="utf-8",
            )
            changed = touch_updated(path)
            text = path.read_text(encoding="utf-8")
            assert changed is True
            assert f"updated: {date.today().strftime('%Y-%m-%d')}" in text


class TestRunIngestSync:
    def test_applies_primary_cascade_and_conflict_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            lit_dir = vault / "03-Knowledge/Literature"
            topic_dir = vault / "03-Knowledge/Topics"
            lit_dir.mkdir(parents=True, exist_ok=True)
            topic_dir.mkdir(parents=True, exist_ok=True)
            primary = lit_dir / "Literature - Attention Survey.md"
            primary.write_text(
                "---\ntype: literature\nupdated: 2026-01-01\n---\n# 核心观点\nold\n",
                encoding="utf-8",
            )
            topic = topic_dir / "Topic - Attention Mechanism.md"
            topic.write_text(
                "---\ntype: topic\nupdated: 2026-01-01\n---\n# 当前结论\nold topic\n",
                encoding="utf-8",
            )
            plan = {
                "primary_fields": {"核心观点": "new primary synthesis"},
                "source_note": "Literature - New Benchmark",
                "source_ref": "OpenAI, 2026-04-13",
                "cascade_updates": [
                    {
                        "target": "03-Knowledge/Topics/Topic - Attention Mechanism.md",
                        "fields": {"当前结论": "new topic conclusion"},
                    }
                ],
                "conflicts": [
                    {
                        "target": "03-Knowledge/Topics/Topic - Attention Mechanism.md",
                        "claim": "New benchmark reverses the old conclusion.",
                        "conflicts_with": "[[Literature - FlashAttention Survey]]",
                    }
                ],
            }
            summary = run_ingest_sync(vault, primary, plan)
            assert summary["primary_updates"]
            assert summary["cascade_updates"]
            assert summary["conflicts"]
            primary_text = primary.read_text(encoding="utf-8")
            topic_text = topic.read_text(encoding="utf-8")
            assert "new primary synthesis" in primary_text
            assert "OpenAI, 2026-04-13" in primary_text
            assert "new topic conclusion" in topic_text
            assert "# Conflicts" in topic_text

    def test_records_updated_notes_in_session_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            lit_dir = vault / "03-Knowledge/Literature"
            topic_dir = vault / "03-Knowledge/Topics"
            lit_dir.mkdir(parents=True, exist_ok=True)
            topic_dir.mkdir(parents=True, exist_ok=True)
            primary = lit_dir / "Literature - Attention Survey.md"
            primary.write_text(
                "---\ntype: literature\nupdated: 2026-01-01\n---\n# 核心观点\nold\n",
                encoding="utf-8",
            )
            topic = topic_dir / "Topic - Attention Mechanism.md"
            topic.write_text(
                "---\ntype: topic\nupdated: 2026-01-01\n---\n# 当前结论\nold topic\n",
                encoding="utf-8",
            )
            plan = {
                "primary_fields": {"核心观点": "new primary synthesis"},
                "cascade_updates": [
                    {
                        "target": "03-Knowledge/Topics/Topic - Attention Mechanism.md",
                        "fields": {"当前结论": "new topic conclusion"},
                    }
                ],
            }
            run_ingest_sync(vault, primary, plan)
            data = json.loads((vault / _SESSION_MEMORY_FILE).read_text(encoding="utf-8"))
            assert "Literature - Attention Survey.md" in data["active_notes"]
            assert "Topic - Attention Mechanism.md" in data["active_notes"]
            assert "Topic - Attention Mechanism" in data["active_topics"]


class TestExtractWikilinks:
    def test_extracts_simple_link(self):
        assert "Concept - RAG" in _extract_wikilinks("see [[Concept - RAG]] here")

    def test_strips_display_text(self):
        assert "Concept - RAG" in _extract_wikilinks("[[Concept - RAG|RAG]]")

    def test_strips_heading_anchor(self):
        assert "Concept - RAG" in _extract_wikilinks("[[Concept - RAG#section]]")

    def test_returns_empty_set_for_plain_text(self):
        assert _extract_wikilinks("no links here") == set()

    def test_extracts_multiple_links(self):
        links = _extract_wikilinks("[[A]] and [[B]]")
        assert "A" in links and "B" in links


class TestLintVault:
    def _make_vault(self, tmp: str) -> Path:
        vault = Path(tmp)
        for d in ["00-Inbox", "01-DailyNotes", "02-Projects",
                  "03-Knowledge/Concepts", "03-Knowledge/Literature",
                  "03-Knowledge/MOCs", "03-Knowledge/Topics", "04-Archive"]:
            (vault / d).mkdir(parents=True, exist_ok=True)
        return vault

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_no_issues_on_clean_vault(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            lint_vault(vault)
            out = capsys.readouterr().out
            assert "No issues found" in out

    def test_detects_broken_wikilink(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            self._write(
                vault / "03-Knowledge/MOCs/MOC - AI.md",
                "---\ntype: moc\nstatus: active\ncreated: 2026-04-01\nupdated: 2026-04-01\n---\n"
                "see [[Concept - NonExistent]]\n"
            )
            lint_vault(vault)
            out = capsys.readouterr().out
            assert "Concept - NonExistent" in out
            assert "Broken links" in out
            events = [
                json.loads(line)
                for line in (vault / _CORRECTIONS_FILE).read_text(encoding="utf-8").splitlines()
            ]
            assert any(event["issue_type"] == "broken-link" for event in events)
            assert any(event["note"].endswith("MOC - AI.md") for event in events)

    def test_detects_orphan_note(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            # A concept note not referenced by anyone
            self._write(
                vault / "03-Knowledge/Concepts/Concept - Orphan.md",
                "---\ntype: concept\nstatus: active\ncreated: 2026-04-01\nupdated: 2026-04-01\n---\n# content\n"
            )
            lint_vault(vault)
            out = capsys.readouterr().out
            assert "Orphan" in out
            assert "Concept - Orphan" in out

    def test_referenced_note_not_orphan(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            self._write(
                vault / "03-Knowledge/Concepts/Concept - Referenced.md",
                "---\ntype: concept\nstatus: active\ncreated: 2026-04-01\nupdated: 2026-04-01\n---\n# content\nsome text here\n"
            )
            self._write(
                vault / "03-Knowledge/MOCs/MOC - AI.md",
                "---\ntype: moc\nstatus: active\ncreated: 2026-04-01\nupdated: 2026-04-01\n---\n"
                "[[Concept - Referenced]]\n"
            )
            lint_vault(vault)
            out = capsys.readouterr().out
            # Should not report orphan for the referenced concept
            assert "Concept - Referenced" not in out or "Orphan" not in out

    def test_detects_inbox_backlog(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            old_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
            self._write(
                vault / "00-Inbox/Literature - Old Draft.md",
                f"---\ntype: literature\nstatus: draft\ncreated: {old_date}\nupdated: {old_date}\n---\n"
            )
            lint_vault(vault)
            out = capsys.readouterr().out
            assert "Inbox backlog" in out
            assert "Literature - Old Draft" in out

    def test_fresh_inbox_note_not_flagged(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            today_str = date.today().strftime("%Y-%m-%d")
            self._write(
                vault / "00-Inbox/Literature - New Draft.md",
                f"---\ntype: literature\nstatus: draft\ncreated: {today_str}\nupdated: {today_str}\n---\n"
            )
            lint_vault(vault)
            out = capsys.readouterr().out
            assert "Inbox backlog" not in out

    def test_detects_skeleton_note(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            self._write(
                vault / "03-Knowledge/Topics/Topic - Skeleton.md",
                "---\ntype: topic\nstatus: active\ncreated: 2026-04-01\nupdated: 2026-04-01\n---\n"
                "# section1\n\n# section2\n\n# section3\n\n# section4\nsome content\n"
            )
            lint_vault(vault)
            out = capsys.readouterr().out
            assert "Skeleton" in out
            assert "Topic - Skeleton" in out

    def test_detects_stale_note(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            old_date = (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")
            self._write(
                vault / "03-Knowledge/Concepts/Concept - Stale.md",
                f"---\ntype: concept\nstatus: active\ncreated: {old_date}\nupdated: {old_date}\n---\n# content\nsome text\n"
            )
            lint_vault(vault)
            out = capsys.readouterr().out
            assert "Stale" in out
            assert "Concept - Stale" in out

    def test_auto_fix_adds_missing_frontmatter_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            note = vault / "03-Knowledge/Concepts/Concept - NoStatus.md"
            self._write(note, "---\ntype: concept\n---\n# content\n")
            lint_vault(vault, auto_fix=True)
            content = note.read_text(encoding="utf-8")
            assert "status:" in content
            assert "created:" in content

    def test_records_missing_frontmatter_in_corrections_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            note = vault / "03-Knowledge/Concepts/Concept - NoStatus.md"
            self._write(note, "---\ntype: concept\n---\n# content\n")
            lint_vault(vault)
            events = [
                json.loads(line)
                for line in (vault / _CORRECTIONS_FILE).read_text(encoding="utf-8").splitlines()
            ]
            assert any(
                event["issue_type"] == "missing-frontmatter"
                and event["note"].endswith("Concept - NoStatus.md")
                for event in events
            )

    def test_auto_fix_does_not_emit_correction_for_fixed_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            note = vault / "03-Knowledge/Concepts/Concept - NoStatus.md"
            self._write(note, "---\ntype: concept\n---\n# content\n")
            lint_vault(vault, auto_fix=True)
            corrections_path = vault / _CORRECTIONS_FILE
            if corrections_path.exists():
                events = [
                    json.loads(line)
                    for line in corrections_path.read_text(encoding="utf-8").splitlines()
                ]
                auto_fixed = any(
                    event["issue_type"] == "missing-frontmatter"
                    and event["note"].endswith("Concept - NoStatus.md")
                    for event in events
                )
                assert not auto_fixed, "auto-fixed fields must not appear as unresolved corrections"

    def test_detects_stale_synthesis(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            (vault / "03-Knowledge/Topics").mkdir(parents=True, exist_ok=True)
            (vault / "03-Knowledge/Literature").mkdir(parents=True, exist_ok=True)

            topic = vault / "03-Knowledge/Topics/Topic - RAG.md"
            literature = vault / "03-Knowledge/Literature/Literature - RAG Paper.md"

            self._write(topic, (
                "---\ntype: topic\nupdated: 2026-01-01\n---\n"
                "# 重要资料\n[[Literature - RAG Paper]]\n"
            ))
            self._write(literature, "---\ntype: literature\nupdated: 2026-03-15\n---\ncontent\n")

            lint_vault(vault)
            events = [
                json.loads(line)
                for line in (vault / _CORRECTIONS_FILE).read_text(encoding="utf-8").splitlines()
            ]
            assert any(e["issue_type"] == "stale-synthesis" for e in events)

    def test_no_stale_synthesis_when_topic_is_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            (vault / "03-Knowledge/Topics").mkdir(parents=True, exist_ok=True)
            (vault / "03-Knowledge/Literature").mkdir(parents=True, exist_ok=True)

            topic = vault / "03-Knowledge/Topics/Topic - RAG.md"
            literature = vault / "03-Knowledge/Literature/Literature - RAG Paper.md"

            self._write(topic, (
                "---\ntype: topic\nupdated: 2026-03-20\n---\n"
                "# 重要资料\n[[Literature - RAG Paper]]\n"
            ))
            self._write(literature, "---\ntype: literature\nupdated: 2026-03-15\n---\ncontent\n")

            lint_vault(vault)
            corrections_path = vault / _CORRECTIONS_FILE
            if corrections_path.exists():
                events = [json.loads(l) for l in corrections_path.read_text(encoding="utf-8").splitlines()]
                assert not any(e["issue_type"] == "stale-synthesis" for e in events)

    def test_cli_lint_runs_successfully(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SCRIPT_PATH),
                 "--type", "lint", "--vault", tmp],
                capture_output=True, text=True, encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[Lint]" in result.stdout


class TestSuggestLinks:
    def _make_vault(self, tmp: str) -> Path:
        vault = Path(tmp)
        for d in ["03-Knowledge/MOCs", "03-Knowledge/Topics",
                  "03-Knowledge/Literature", "03-Knowledge/Concepts"]:
            (vault / d).mkdir(parents=True, exist_ok=True)
        return vault

    def _write(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def test_suggests_moc_that_mentions_keyword(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            moc = vault / "03-Knowledge/MOCs/MOC - Transformer.md"
            self._write(moc, "---\ntype: moc\n---\n# 资料\nsome Transformer content\n")
            new_note = vault / "03-Knowledge/Literature/Literature - Transformer Survey.md"
            self._write(new_note, "---\ntype: literature\n---\ncontent\n")
            suggestions = suggest_links(vault, new_note)
            paths = [str(s[0]) for s in suggestions]
            assert any("MOC - Transformer" in p for p in paths)
            assert any("strength=medium" in s[1] and "title=Transformer" in s[1] for s in suggestions)

    def test_no_suggestion_when_already_linked(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            new_note = vault / "03-Knowledge/Literature/Literature - Attention Survey.md"
            self._write(new_note, "---\ntype: literature\n---\ncontent\n")
            moc = vault / "03-Knowledge/MOCs/MOC - Attention.md"
            self._write(moc, f"---\ntype: moc\n---\n[[Literature - Attention Survey]]\n")
            suggestions = suggest_links(vault, new_note)
            paths = [str(s[0]) for s in suggestions]
            assert not any("MOC - Attention" in p for p in paths)

    def test_no_suggestion_when_no_keyword_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            moc = vault / "03-Knowledge/MOCs/MOC - Cooking.md"
            self._write(moc, "---\ntype: moc\n---\n# 资料\nrecipes and food\n")
            new_note = vault / "03-Knowledge/Literature/Literature - Quantum Computing.md"
            self._write(new_note, "---\ntype: literature\n---\ncontent\n")
            suggestions = suggest_links(vault, new_note)
            assert suggestions == []

    def test_suggests_topic_as_well_as_moc(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            topic = vault / "03-Knowledge/Topics/Topic - Attention Mechanism.md"
            self._write(topic, "---\ntype: topic\n---\n# 重要资料\nAttention research\n")
            new_note = vault / "03-Knowledge/Literature/Literature - Attention Survey.md"
            self._write(new_note, "---\ntype: literature\n---\ncontent\n")
            suggestions = suggest_links(vault, new_note)
            paths = [str(s[0]) for s in suggestions]
            assert any("Topic - Attention" in p for p in paths)
            assert "Topic - Attention Mechanism" in paths[0]
            assert "strength=high" in suggestions[0][1]

    def test_topic_can_match_by_body_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            topic = vault / "03-Knowledge/Topics/Topic - Media Transport.md"
            self._write(
                topic,
                "---\ntype: topic\n---\n# 主题说明\nWebRTC bitrate adaptation and packet loss handling\n",
            )
            new_note = vault / "03-Knowledge/Literature/Literature - Bitrate Control Survey.md"
            self._write(new_note, "---\ntype: literature\n---\ncontent\n")
            suggestions = suggest_links(vault, new_note)
            paths = [str(s[0]) for s in suggestions]
            assert any("Topic - Media Transport" in p for p in paths)
            assert any("body=Bitrate" in s[1] or "body=Control" in s[1] for s in suggestions)

    def test_ignores_collision_date_suffix_in_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            topic = vault / "03-Knowledge/Topics/Topic - RAG.md"
            self._write(topic, "---\ntype: topic\n---\n# 閲嶈璧勬枡\nRAG system design\n")
            new_note = vault / "03-Knowledge/Literature/Literature - RAG 2026-04-10.md"
            self._write(new_note, "---\ntype: literature\n---\ncontent\n")
            suggestions = suggest_links(vault, new_note)
            assert any("Topic - RAG" in str(path) for path, _ in suggestions)
            assert all("2026" not in reason for _, reason in suggestions)

    def test_reject_feedback_downranks_previous_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            topic = vault / "03-Knowledge/Topics/Topic - Attention Mechanism.md"
            moc = vault / "03-Knowledge/MOCs/MOC - Attention.md"
            self._write(topic, "---\ntype: topic\n---\n# 重要资料\nAttention research\n")
            self._write(moc, "---\ntype: moc\n---\n# 资料\nAttention links\n")
            new_note = vault / "03-Knowledge/Literature/Literature - Attention Survey.md"
            self._write(new_note, "---\ntype: literature\n---\ncontent\n")

            append_suggestion_feedback(
                vault,
                suggestion_type="link",
                action="reject",
                source_note="Literature - Attention Survey",
                target_notes=["Topic - Attention Mechanism"],
                reason="too broad",
            )

            suggestions = suggest_links(vault, new_note)
            paths = [Path(path).as_posix() for path, _ in suggestions]
            assert "03-Knowledge/MOCs/MOC - Attention.md" in paths[0]
            assert all("Topic - Attention Mechanism" not in Path(path).as_posix() for path, _ in suggestions)

    def test_same_session_rejection_downranks_target_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            topic = vault / "03-Knowledge/Topics/Topic - Attention Mechanism.md"
            moc = vault / "03-Knowledge/MOCs/MOC - Attention.md"
            self._write(topic, "---\ntype: topic\n---\n# 重要资料\nAttention research\n")
            self._write(moc, "---\ntype: moc\n---\n# 资料\nAttention links\n")
            new_note = vault / "03-Knowledge/Literature/Literature - Attention Survey.md"
            self._write(new_note, "---\ntype: literature\n---\ncontent\n")

            append_suggestion_feedback(
                vault,
                suggestion_type="link",
                action="reject",
                source_note="Literature - Attention Survey",
                target_notes=["Topic - Attention Mechanism"],
                reason="too broad in this session",
            )

            suggestions = suggest_links(vault, new_note)
            assert "MOC - Attention.md" in Path(suggestions[0][0]).name
            assert all("Topic - Attention Mechanism" not in Path(path).stem for path, _ in suggestions)


class TestOrphanOnCreate:
    def _make_vault(self, tmp: str) -> Path:
        vault = Path(tmp)
        for d in ["03-Knowledge/Literature", "03-Knowledge/Topics", "03-Knowledge/MOCs"]:
            (vault / d).mkdir(parents=True, exist_ok=True)
        return vault

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_emits_correction_when_no_topic_match(self):
        from skills.obsidian.obsidian_writer import _maybe_emit_orphan_correction
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            note = vault / "03-Knowledge/Literature/Literature - Test.md"
            self._write(note, "---\ntype: literature\n---\ncontent\n")
            # No suggestions (no topic match)
            _maybe_emit_orphan_correction(vault, note, [], is_draft=False)
            events = [
                json.loads(line)
                for line in (vault / _CORRECTIONS_FILE).read_text(encoding="utf-8").splitlines()
            ]
            assert any(e["issue_type"] == "orphan-on-create" for e in events)

    def test_no_correction_when_topic_match_exists(self):
        from skills.obsidian.obsidian_writer import _maybe_emit_orphan_correction
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            note = vault / "03-Knowledge/Literature/Literature - Test.md"
            self._write(note, "---\ntype: literature\n---\ncontent\n")
            topic = Path("03-Knowledge/Topics/Topic - Something.md")
            _maybe_emit_orphan_correction(vault, note, [(topic, "重要资料")], is_draft=False)
            assert not (vault / _CORRECTIONS_FILE).exists()

    def test_no_correction_for_draft(self):
        from skills.obsidian.obsidian_writer import _maybe_emit_orphan_correction
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            note = vault / "03-Knowledge/Literature/Literature - Test.md"
            self._write(note, "---\ntype: literature\n---\ncontent\n")
            _maybe_emit_orphan_correction(vault, note, [], is_draft=True)
            assert not (vault / _CORRECTIONS_FILE).exists()


class TestTopicScout:
    def _make_vault(self, tmp: str) -> Path:
        vault = Path(tmp)
        for d in ["00-Inbox", "03-Knowledge/Literature", "03-Knowledge/Topics"]:
            (vault / d).mkdir(parents=True, exist_ok=True)
        return vault

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_clusters_related_orphan_notes(self, capsys):
        from skills.obsidian.obsidian_writer import scout_topics
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            self._write(
                vault / "03-Knowledge/Literature/Literature - KV Cache.md",
                "---\ntype: literature\n---\nKV cache inference transformer attention memory\n",
            )
            self._write(
                vault / "03-Knowledge/Literature/Literature - Speculative Decoding.md",
                "---\ntype: literature\n---\nspeculative decoding inference transformer latency\n",
            )
            # Unrelated note — should end up as singleton
            self._write(
                vault / "03-Knowledge/Literature/Literature - Piano Chords.md",
                "---\ntype: literature\n---\npiano chord music harmony scale\n",
            )
            scout_topics(vault)
            out = capsys.readouterr().out
            assert "Cluster" in out
            assert "KV Cache" in out
            assert "Speculative Decoding" in out

    def test_excludes_parented_notes(self, capsys):
        from skills.obsidian.obsidian_writer import scout_topics
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            self._write(
                vault / "03-Knowledge/Literature/Literature - KV Cache.md",
                "---\ntype: literature\n---\ncontent\n",
            )
            # Topic already links to KV Cache → it should be excluded from scout
            self._write(
                vault / "03-Knowledge/Topics/Topic - Inference.md",
                "---\ntype: topic\n---\n# 重要资料\n[[Literature - KV Cache]]\n",
            )
            scout_topics(vault)
            out = capsys.readouterr().out
            assert "KV Cache" not in out

    def test_no_orphans_message_when_all_parented(self, capsys):
        from skills.obsidian.obsidian_writer import scout_topics
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            self._write(
                vault / "03-Knowledge/Topics/Topic - Inference.md",
                "---\ntype: topic\n---\n# 重要资料\n[[Literature - KV Cache]]\n",
            )
            self._write(
                vault / "03-Knowledge/Literature/Literature - KV Cache.md",
                "---\ntype: literature\n---\ncontent\n",
            )
            scout_topics(vault)
            out = capsys.readouterr().out
            assert "No orphan notes found" in out


class TestFindMergeCandidates:
    def test_returns_matching_literature_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            lit_dir = vault / "03-Knowledge/Literature"
            lit_dir.mkdir(parents=True, exist_ok=True)
            (lit_dir / "Literature - Attention Is All You Need.md").write_text(
                "---\ntype: literature\n---\nattention transformer architecture\n",
                encoding="utf-8",
            )
            (lit_dir / "Literature - Cooking Notes.md").write_text(
                "---\ntype: literature\n---\nrecipes\n",
                encoding="utf-8",
            )
            candidates = find_merge_candidates(vault, "Attention Survey")
            assert any("Attention Is All You Need" in str(path) for path in candidates)


class TestFindCascadeCandidates:
    def test_returns_matching_topic_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "03-Knowledge/Topics").mkdir(parents=True, exist_ok=True)
            (vault / "03-Knowledge/Literature").mkdir(parents=True, exist_ok=True)
            (vault / "03-Knowledge/Topics/Topic - Attention Mechanism.md").write_text(
                "---\ntype: topic\n---\n# 重要资料\nAttention research\n",
                encoding="utf-8",
            )
            source_note = vault / "03-Knowledge/Literature/Literature - Attention Survey.md"
            source_note.write_text("---\ntype: literature\n---\ncontent\n", encoding="utf-8")
            candidates = find_cascade_candidates(vault, source_note)
            assert any("Topic - Attention Mechanism" in str(path) for path, _ in candidates)


class TestSuggestNewTopic:
    def test_suggests_new_topic_when_no_topic_match_exists(self):
        new_note = Path("03-Knowledge/Literature/Literature - Bitrate Control Survey.md")
        suggestions = [(Path("03-Knowledge/MOCs/MOC - Streaming.md"), "# 资料; strength=medium; title=Streaming")]
        hint = suggest_new_topic(new_note, suggestions)
        assert "Topic - Bitrate Control" in hint

    def test_skips_new_topic_hint_when_topic_match_exists(self):
        new_note = Path("03-Knowledge/Literature/Literature - Attention Survey.md")
        suggestions = [(Path("03-Knowledge/Topics/Topic - Attention Mechanism.md"), "# 重要资料; strength=high; title=Attention")]
        hint = suggest_new_topic(new_note, suggestions)
        assert hint == ""


    def test_skips_new_topic_hint_for_new_topic_note_itself(self):
        new_note = Path("03-Knowledge/Topics/Topic - RAG.md")
        hint = suggest_new_topic(new_note, [])
        assert hint == ""


class TestTopicCandidateFromStem:
    def test_strips_note_type_prefix_and_generic_suffix(self):
        candidate = _topic_candidate_from_stem("Literature - Bitrate Control Survey")
        assert candidate == "Bitrate Control"

    def test_keeps_meaningful_multiword_phrase(self):
        candidate = _topic_candidate_from_stem("Project - WebRTC Packet Loss Debugging Notes")
        assert candidate == "WebRTC Packet Loss Debugging"


class TestSuggestionKeywordsFromStem:
    def test_allows_three_letter_uppercase_acronyms(self):
        keywords = _suggestion_keywords_from_stem("Literature - RAG")
        assert keywords == ["RAG"]

    def test_strips_collision_date_suffix(self):
        keywords = _suggestion_keywords_from_stem("Topic - RAG 2026-04-10")
        assert keywords == ["RAG"]


class TestRebuildIndex:
    def _make_vault(self, tmp: str) -> Path:
        vault = Path(tmp)
        for d in ["02-Projects", "03-Knowledge/Topics", "03-Knowledge/MOCs",
                  "03-Knowledge/Concepts", "03-Knowledge/Literature"]:
            (vault / d).mkdir(parents=True, exist_ok=True)
        return vault

    def _write(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def test_creates_index_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            index_path = rebuild_index(vault)
            assert index_path.exists()
            assert index_path.name == _INDEX_FILE

    def test_index_contains_note_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            today = date.today().strftime("%Y-%m-%d")
            self._write(
                vault / "03-Knowledge/Concepts/Concept - Transformer.md",
                f"---\ntype: concept\nstatus: active\nupdated: {today}\n---\n# content\n"
            )
            rebuild_index(vault)
            text = (vault / _INDEX_FILE).read_text(encoding="utf-8")
            assert "Concept - Transformer" in text

    def test_index_has_section_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            today = date.today().strftime("%Y-%m-%d")
            self._write(
                vault / "03-Knowledge/Literature/Literature - Test.md",
                f"---\ntype: literature\nstatus: active\nupdated: {today}\n---\n"
            )
            rebuild_index(vault)
            text = (vault / _INDEX_FILE).read_text(encoding="utf-8")
            assert "## Literature" in text

    def test_write_note_increments_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            rebuild_index(vault)
            write_note(vault, "concept", "Self-Attention",
                       {"一句话定义": "key mechanism", "核心机制": "dot product"},
                       is_draft=False)
            text = (vault / _INDEX_FILE).read_text(encoding="utf-8")
            assert "Concept - Self-Attention" in text

    def test_draft_note_not_added_to_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._make_vault(tmp)
            rebuild_index(vault)
            write_note(vault, "literature", "Draft Paper", {}, is_draft=True)
            text = (vault / _INDEX_FILE).read_text(encoding="utf-8")
            assert "Draft Paper" not in text

    def test_cli_index_runs_successfully(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SCRIPT_PATH),
                 "--type", "index", "--vault", tmp],
                capture_output=True, text=True, encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[OK] Index rebuilt" in result.stdout


class TestCLI:
    def test_dry_run_prints_ingest_preview_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "topic",
                    "--title", "RAG",
                    "--fields", '{"主题说明": "overview"}',
                    "--draft", "false",
                    "--vault", tmp,
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[INGEST PREVIEW]" in result.stdout
            assert "Action  : create" in result.stdout
            assert "RAG" in result.stdout
            # No file written
            assert not list(Path(tmp).rglob("*.md"))

    def test_write_mode_outputs_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "topic",
                    "--title", "RAG",
                    "--fields", '{"主题说明": "overview", "当前结论": "retrieval improves grounding"}',
                    "--draft", "false",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[OK] Written:" in result.stdout
            assert (Path(tmp) / _LOG_FILE).exists()

    def test_query_mode_outputs_tier1_topics(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic_dir = Path(tmp) / "03-Knowledge/Topics"
            topic_dir.mkdir(parents=True, exist_ok=True)
            (topic_dir / "Topic - RAG.md").write_text(
                "---\ntype: topic\n---\n"
                "# 主题说明\nRAG overview\n\n"
                "# 当前结论\nDense retrieval reduces hallucination\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "query",
                    "--query", "rag hallucination",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[Tier 1: Topics]" in result.stdout
            assert "[[Topic - RAG]]" in result.stdout
            assert "Dense retrieval reduces hallucination" in result.stdout

    def test_query_mode_with_details_outputs_grouped_notes_and_orphans(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic_dir = Path(tmp) / "03-Knowledge/Topics"
            lit_dir = Path(tmp) / "03-Knowledge/Literature"
            topic_dir.mkdir(parents=True, exist_ok=True)
            lit_dir.mkdir(parents=True, exist_ok=True)
            (topic_dir / "Topic - Attention Mechanism.md").write_text(
                "---\ntype: topic\n---\n"
                "# 主题说明\nAttention overview\n\n"
                "# 当前结论\nAttention remains important\n",
                encoding="utf-8",
            )
            (lit_dir / "Literature - Attention Survey.md").write_text(
                "---\ntype: literature\n---\n"
                "# 核心观点\nAttention improves sequence modeling\n\n"
                "# 知识连接\n[[Topic - Attention Mechanism]]\n",
                encoding="utf-8",
            )
            (lit_dir / "Literature - Attention Benchmark.md").write_text(
                "---\ntype: literature\n---\n"
                "# 核心观点\nAttention benchmark highlights latency tradeoffs\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "query",
                    "--query", "attention",
                    "--details",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[Tier 2: Details]" in result.stdout
            assert "Topic: [[Topic - Attention Mechanism]]" in result.stdout
            assert "[[Literature - Attention Survey]]" in result.stdout
            assert "[Orphans]" in result.stdout
            assert "[[Literature - Attention Benchmark]]" in result.stdout

    def test_organize_mode_outputs_matches_and_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic_dir = Path(tmp) / "03-Knowledge/Topics"
            lit_dir = Path(tmp) / "03-Knowledge/Literature"
            inbox_dir = Path(tmp) / "00-Inbox"
            topic_dir.mkdir(parents=True, exist_ok=True)
            lit_dir.mkdir(parents=True, exist_ok=True)
            inbox_dir.mkdir(parents=True, exist_ok=True)
            (topic_dir / "Topic - Attention Mechanism.md").write_text(
                "---\ntype: topic\n---\n# 当前结论\nattention summary\n",
                encoding="utf-8",
            )
            (lit_dir / "Literature - Attention Survey.md").write_text(
                "---\ntype: literature\n---\n# 核心观点\nattention details\n",
                encoding="utf-8",
            )
            (inbox_dir / "Literature - Attention Draft.md").write_text(
                "---\ntype: literature\nstatus: draft\n---\n# 核心观点\nattention draft\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "organize",
                    "--query", "attention",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[Organize] attention" in result.stdout
            assert "[Matches]" in result.stdout
            assert "[[Literature - Attention Survey]]" in result.stdout
            assert "[Suggest] Converge into: topic" in result.stdout
            assert "[Reasons]" in result.stdout

    def test_merge_candidates_mode_lists_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            lit_dir = Path(tmp) / "03-Knowledge/Literature"
            lit_dir.mkdir(parents=True, exist_ok=True)
            (lit_dir / "Literature - Attention Is All You Need.md").write_text(
                "---\ntype: literature\n---\nattention transformer architecture\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "merge-candidates",
                    "--title", "Attention Survey",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[Merge candidates]" in result.stdout
            assert "Attention Is All You Need" in result.stdout
            assert "[Feedback hint]" in result.stdout
            assert "--suggestion-type merge" in result.stdout

    def test_write_mode_supports_post_write_source_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "topic",
                    "--title", "RAG",
                    "--fields", '{"主题说明": "overview", "当前结论": "retrieval improves grounding"}',
                    "--draft", "false",
                    "--vault", tmp,
                    "--source-note", "Literature - RAG Survey",
                    "--source-ref", "Anthropic, 2026-04-13",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            note_text = (Path(tmp) / "03-Knowledge/Topics/Topic - RAG.md").read_text(encoding="utf-8")
            assert "# Supporting notes" in note_text
            assert "[[Literature - RAG Survey]]" in note_text
            assert "# Sources" in note_text
            assert "Anthropic, 2026-04-13" in note_text

    def test_merge_update_mode_updates_note_and_logs_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            lit_dir = Path(tmp) / "03-Knowledge/Literature"
            lit_dir.mkdir(parents=True, exist_ok=True)
            target = lit_dir / "Literature - Attention Is All You Need.md"
            target.write_text(
                "---\ntype: literature\nupdated: 2026-01-01\n---\n# 核心观点\nold\n\n# 方法要点\nold method\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "merge-update",
                    "--target", "03-Knowledge/Literature/Literature - Attention Is All You Need.md",
                    "--fields", '{"核心观点": "new synthesis", "方法要点": "new method"}',
                    "--vault", tmp,
                    "--source-note", "Literature - Attention Survey",
                    "--source-ref", "OpenAI, 2026-04-13",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            text = target.read_text(encoding="utf-8")
            assert "new synthesis" in text
            assert "new method" in text
            assert "[[Literature - Attention Survey]]" in text
            assert "OpenAI, 2026-04-13" in text
            assert f"updated: {date.today().strftime('%Y-%m-%d')}" in text
            log_text = (Path(tmp) / _LOG_FILE).read_text(encoding="utf-8")
            assert "merge | Literature - Attention Is All You Need" in log_text

    def test_cascade_candidates_mode_lists_matching_topics(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "03-Knowledge/Topics").mkdir(parents=True, exist_ok=True)
            (Path(tmp) / "03-Knowledge/Literature").mkdir(parents=True, exist_ok=True)
            (Path(tmp) / "03-Knowledge/Topics/Topic - Attention Mechanism.md").write_text(
                "---\ntype: topic\n---\n# 重要资料\nAttention research\n",
                encoding="utf-8",
            )
            source_note = Path(tmp) / "03-Knowledge/Literature/Literature - Attention Survey.md"
            source_note.write_text("---\ntype: literature\n---\ncontent\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "cascade-candidates",
                    "--target", "03-Knowledge/Literature/Literature - Attention Survey.md",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[Cascade candidates]" in result.stdout
            assert "Topic - Attention Mechanism" in result.stdout
            assert "[Feedback hint]" in result.stdout
            assert "--suggestion-type cascade" in result.stdout

    def test_cascade_update_mode_updates_topic_and_logs_cascade(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic_dir = Path(tmp) / "03-Knowledge/Topics"
            topic_dir.mkdir(parents=True, exist_ok=True)
            target = topic_dir / "Topic - Attention Mechanism.md"
            target.write_text(
                "---\ntype: topic\nupdated: 2026-01-01\n---\n# 当前结论\nold\n\n# 重要资料\nold refs\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "cascade-update",
                    "--target", "03-Knowledge/Topics/Topic - Attention Mechanism.md",
                    "--fields", '{"当前结论": "new conclusion", "重要资料": "[[Literature - Attention Survey]]"}',
                    "--vault", tmp,
                    "--source-note", "Literature - Attention Survey",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            text = target.read_text(encoding="utf-8")
            assert "new conclusion" in text
            assert "[[Literature - Attention Survey]]" in text
            assert "# Supporting notes" in text
            assert f"updated: {date.today().strftime('%Y-%m-%d')}" in text
            log_text = (Path(tmp) / _LOG_FILE).read_text(encoding="utf-8")
            assert "cascade | Topic - Attention Mechanism" in log_text

    def test_cascade_update_rejects_non_topic_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic_dir = Path(tmp) / "03-Knowledge/Topics"
            topic_dir.mkdir(parents=True, exist_ok=True)
            target = topic_dir / "Topic - Attention Mechanism.md"
            target.write_text("---\ntype: topic\n---\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "cascade-update",
                    "--target", "03-Knowledge/Topics/Topic - Attention Mechanism.md",
                    "--fields", '{"核心机制": "should fail"}',
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode != 0
            assert "cascade-update only supports topic fields" in result.stderr

    def test_conflict_update_mode_adds_conflict_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic_dir = Path(tmp) / "03-Knowledge/Topics"
            topic_dir.mkdir(parents=True, exist_ok=True)
            target = topic_dir / "Topic - Attention Mechanism.md"
            target.write_text("---\ntype: topic\nupdated: 2026-01-01\n---\n# 当前结论\nold\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "conflict-update",
                    "--target", "03-Knowledge/Topics/Topic - Attention Mechanism.md",
                    "--fields", '{"claim": "New benchmark reverses the old conclusion."}',
                    "--vault", tmp,
                    "--source-note", "Literature - New Benchmark",
                    "--conflicts-with", "[[Literature - FlashAttention Survey]]",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            text = target.read_text(encoding="utf-8")
            assert "# Conflicts" in text
            assert "Source: [[Literature - New Benchmark]]" in text
            assert "Claim: New benchmark reverses the old conclusion." in text
            assert f"updated: {date.today().strftime('%Y-%m-%d')}" in text
            log_text = (Path(tmp) / _LOG_FILE).read_text(encoding="utf-8")
            assert "conflict | Topic - Attention Mechanism" in log_text

    def test_conflict_update_requires_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic_dir = Path(tmp) / "03-Knowledge/Topics"
            topic_dir.mkdir(parents=True, exist_ok=True)
            target = topic_dir / "Topic - Attention Mechanism.md"
            target.write_text("---\ntype: topic\n---\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "conflict-update",
                    "--target", "03-Knowledge/Topics/Topic - Attention Mechanism.md",
                    "--fields", '{}',
                    "--vault", tmp,
                    "--source-note", "Literature - New Benchmark",
                    "--conflicts-with", "[[Literature - FlashAttention Survey]]",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode != 0
            assert "conflict-update requires fields.claim" in result.stderr

    def test_suggestion_feedback_mode_writes_event_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "suggestion-feedback",
                    "--vault", tmp,
                    "--suggestion-type", "link",
                    "--feedback-action", "modify-accept",
                    "--source-note", "Literature - Attention Survey",
                    "--targets", "Topic - Attention,MOC - Transformers",
                    "--reason", "linked to narrower topic instead",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "Suggestion feedback recorded" in result.stdout
            events = [
                json.loads(line)
                for line in (Path(tmp) / _EVENTS_FILE).read_text(encoding="utf-8").splitlines()
            ]
            assert events[0]["action"] == "modify-accept"
            assert events[0]["suggestion_type"] == "link"
            assert events[0]["target_notes"] == ["Topic - Attention", "MOC - Transformers"]
            log_text = (Path(tmp) / _LOG_FILE).read_text(encoding="utf-8")
            assert "suggestion-feedback | Literature - Attention Survey" in log_text

    def test_suggestion_feedback_mode_normalizes_path_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "suggestion-feedback",
                    "--vault", tmp,
                    "--suggestion-type", "link",
                    "--feedback-action", "reject",
                    "--source-note", "Literature - Attention Survey",
                    "--targets", "03-Knowledge/Topics/Topic - Attention.md",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            events = [
                json.loads(line)
                for line in (Path(tmp) / _EVENTS_FILE).read_text(encoding="utf-8").splitlines()
            ]
            assert events[0]["target_notes"] == ["Topic - Attention"]
            assert "Targets: Topic - Attention" in result.stdout

    def test_ingest_sync_mode_runs_full_update_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            lit_dir = Path(tmp) / "03-Knowledge/Literature"
            topic_dir = Path(tmp) / "03-Knowledge/Topics"
            lit_dir.mkdir(parents=True, exist_ok=True)
            topic_dir.mkdir(parents=True, exist_ok=True)
            primary = lit_dir / "Literature - Attention Survey.md"
            primary.write_text(
                "---\ntype: literature\nupdated: 2026-01-01\n---\n# 核心观点\nold\n",
                encoding="utf-8",
            )
            topic = topic_dir / "Topic - Attention Mechanism.md"
            topic.write_text(
                "---\ntype: topic\nupdated: 2026-01-01\n---\n# 当前结论\nold topic\n",
                encoding="utf-8",
            )
            plan = (
                '{'
                '"primary_fields":{"核心观点":"new primary synthesis"},'
                '"source_note":"Literature - New Benchmark",'
                '"source_ref":"OpenAI, 2026-04-13",'
                '"cascade_updates":[{"target":"03-Knowledge/Topics/Topic - Attention Mechanism.md","fields":{"当前结论":"new topic conclusion"}}],'
                '"conflicts":[{"target":"03-Knowledge/Topics/Topic - Attention Mechanism.md","claim":"New benchmark reverses the old conclusion.","conflicts_with":"[[Literature - FlashAttention Survey]]"}]'
                '}'
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "ingest-sync",
                    "--target", "03-Knowledge/Literature/Literature - Attention Survey.md",
                    "--fields", plan,
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[OK] Ingest sync applied" in result.stdout
            primary_text = primary.read_text(encoding="utf-8")
            topic_text = topic.read_text(encoding="utf-8")
            assert "new primary synthesis" in primary_text
            assert "new topic conclusion" in topic_text
            assert "# Conflicts" in topic_text

    def test_write_mode_prints_topic_suggestion_when_no_topic_match_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "literature",
                    "--title", "Bitrate Control Survey",
                    "--fields", '{"核心观点": "x", "方法要点": "y"}',
                    "--draft", "false",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[Topic suggestion]" in result.stdout
            assert "Topic - Bitrate Control" in result.stdout
            assert "[Feedback hint]" in result.stdout
            assert "--suggestion-type topic" in result.stdout

    def test_write_mode_skips_topic_suggestion_when_topic_match_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic_dir = Path(tmp) / "03-Knowledge/Topics"
            topic_dir.mkdir(parents=True, exist_ok=True)
            (topic_dir / "Topic - Attention Mechanism.md").write_text(
                "---\ntype: topic\n---\n# 重要资料\nAttention research\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "literature",
                    "--title", "Attention Survey",
                    "--fields", '{"核心观点": "x", "方法要点": "y"}',
                    "--draft", "false",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[Link suggestions]" in result.stdout
            assert "[Topic suggestion]" not in result.stdout
            assert "[Feedback hint]" in result.stdout
            assert "--suggestion-type link" in result.stdout

    def test_write_mode_does_not_suggest_topic_for_topic_note_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "topic",
                    "--title", "RAG",
                    "--fields", '{"涓婚璇存槑": "overview", "褰撳墠缁撹": "retrieval improves grounding"}',
                    "--draft", "false",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[Topic suggestion]" not in result.stdout

    def test_fleeting_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "fleeting",
                    "--fields", '{"content": "测试想法", "tags": "#test"}',
                    "--vault", tmp,
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0
            assert "[DRY RUN]" in result.stdout
            assert "测试想法" in result.stdout

    def test_fleeting_missing_content_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--type", "fleeting",
                    "--fields", '{}',
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
            )
            assert result.returncode != 0


class TestClassifyIngestAction:
    def test_create_when_no_collision(self, tmp_path):
        (tmp_path / "03-Knowledge/Topics").mkdir(parents=True)
        action, existing, planned = _classify_ingest_action(
            tmp_path, "topic", "RAG", is_draft=False
        )
        assert action == "create"
        assert existing is None
        assert planned.name == "Topic - RAG.md"

    def test_dated_copy_when_base_exists(self, tmp_path):
        lit_dir = tmp_path / "03-Knowledge/Topics"
        lit_dir.mkdir(parents=True)
        (lit_dir / "Topic - RAG.md").write_text("existing", encoding="utf-8")

        action, existing, planned = _classify_ingest_action(
            tmp_path, "topic", "RAG", is_draft=False
        )
        today = date.today().strftime("%Y-%m-%d")
        assert action == "create (dated copy)"
        assert existing is not None
        assert existing.name == "Topic - RAG.md"
        assert planned.name == f"Topic - RAG {today}.md"

    def test_create_in_inbox_when_draft(self, tmp_path):
        (tmp_path / "00-Inbox").mkdir(parents=True)
        action, existing, planned = _classify_ingest_action(
            tmp_path, "topic", "RAG", is_draft=True
        )
        assert action == "create"
        assert existing is None
        assert "00-Inbox" in str(planned)


class TestSectionDiffSummary:
    def _make_note(self, tmp_path, name, sections: dict) -> Path:
        lines = ["---\ntype: test\n---\n"]
        for title, body in sections.items():
            lines.append(f"# {title}\n{body}\n")
        path = tmp_path / name
        path.write_text("".join(lines), encoding="utf-8")
        return path

    def test_empty_to_filled_section(self, tmp_path):
        existing = self._make_note(tmp_path, "old.md", {"核心观点": "", "方法要点": ""})
        new_content = "# 核心观点\n新内容很长很长很长\n# 方法要点\n"
        summary = _section_diff_summary(existing, new_content)
        assert "核心观点" in summary
        assert "empty→" in summary

    def test_changed_section(self, tmp_path):
        existing = self._make_note(tmp_path, "old.md", {"核心观点": "旧内容abc"})
        new_content = "# 核心观点\n新内容xyz更长一些\n"
        summary = _section_diff_summary(existing, new_content)
        assert "核心观点" in summary
        assert "c→" in summary

    def test_no_diff_when_identical(self, tmp_path):
        existing = self._make_note(tmp_path, "old.md", {"核心观点": "内容相同"})
        new_content = "# 核心观点\n内容相同\n"
        summary = _section_diff_summary(existing, new_content)
        assert summary == "no section differences"


class TestIngestPreviewCLI:
    """End-to-end tests for the --dry-run ingest preview output."""

    def _run(self, tmp, extra_args=None):
        cmd = [
            sys.executable,
            str(SCRIPT_PATH),
            "--type", "literature",
            "--title", "Test Paper",
            "--fields", '{"核心观点": "key finding", "方法要点": "method detail"}',
            "--draft", "false",
            "--vault", tmp,
            "--dry-run",
        ]
        if extra_args:
            cmd.extend(extra_args)
        return subprocess.run(
            cmd,
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(REPO_ROOT),
        )

    def test_create_action_shown_for_new_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            assert result.returncode == 0
            assert "[INGEST PREVIEW]" in result.stdout
            assert "Action  : create" in result.stdout
            assert "Target  :" in result.stdout
            # no file written
            assert not list(Path(tmp).rglob("*.md"))

    def test_dated_copy_action_shown_when_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            lit_dir = Path(tmp) / "03-Knowledge/Literature"
            lit_dir.mkdir(parents=True)
            (lit_dir / "Literature - Test Paper.md").write_text(
                "---\ntype: literature\n---\n# 核心观点\nold finding\n",
                encoding="utf-8",
            )
            result = self._run(tmp)
            assert result.returncode == 0
            assert "Action  : create (dated copy)" in result.stdout
            assert "Existing:" in result.stdout
            assert "Diff    :" in result.stdout
            assert "merge-update" in result.stdout  # hint line present

    def test_topic_suggestion_shown_even_without_link_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Empty vault — no Topics/MOCs exist, so suggest_links returns []
            result = self._run(tmp)
            assert result.returncode == 0
            # suggest_new_topic should still fire
            assert "[Topic suggestion]" in result.stdout
            assert "[Feedback hint]" in result.stdout
            assert "--suggestion-type topic" in result.stdout

    def test_link_suggestions_shown_when_matching_topic_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            topic_dir = Path(tmp) / "03-Knowledge/Topics"
            topic_dir.mkdir(parents=True)
            (topic_dir / "Topic - Test Research.md").write_text(
                "---\ntype: topic\n---\n# 重要资料\n\n# 当前结论\nTest is important\n",
                encoding="utf-8",
            )
            result = self._run(tmp)
            assert result.returncode == 0
            assert "[Link suggestions]" in result.stdout
            assert "[Feedback hint]" in result.stdout
            assert "--suggestion-type link" in result.stdout


class TestMemoryIntegration:
    """写笔记后，memory_manager 自动被调用。"""

    def test_write_concept_note_seeds_memory(self, tmp_path):
        """写入 concept 笔记后，_memory.jsonl 中应出现该词条。"""
        import json
        from skills.obsidian.memory_manager import MemoryManager, _MEMORY_FILE

        vault = tmp_path
        # 创建必要目录
        (vault / "03-Knowledge" / "Concepts").mkdir(parents=True)

        write_note(
            vault=vault,
            note_type="concept",
            title="Transformer",
            fields={"一句话定义": "注意力机制架构", "核心机制": "self-attention"},
            is_draft=False,
        )

        memory_file = vault / _MEMORY_FILE
        assert memory_file.exists(), "_memory.jsonl 应被创建"
        entries = [json.loads(l) for l in memory_file.read_text(encoding="utf-8").splitlines() if l]
        words = [e["word"] for e in entries]
        assert "Transformer" in words
