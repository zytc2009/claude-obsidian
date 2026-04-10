import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from skills.obsidian.obsidian_writer import (
    NOTE_CONFIG,
    _INDEX_FILE,
    _append_to_index,
    _extract_wikilinks,
    _parse_frontmatter,
    _suggestion_keywords_from_stem,
    append_fleeting,
    get_target_path,
    is_draft_by_content,
    lint_vault,
    make_filename,
    rebuild_index,
    render_concept,
    render_literature,
    render_project,
    render_topic,
    _topic_candidate_from_stem,
    suggest_links,
    suggest_new_topic,
    write_note,
)


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

    def test_cli_lint_runs_successfully(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "skills/obsidian/obsidian_writer.py",
                 "--type", "lint", "--vault", tmp],
                capture_output=True, text=True, encoding="utf-8",
                cwd="D:/AI/claude_code/claude-obsidian",
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
                [sys.executable, "skills/obsidian/obsidian_writer.py",
                 "--type", "index", "--vault", tmp],
                capture_output=True, text=True, encoding="utf-8",
                cwd="D:/AI/claude_code/claude-obsidian",
            )
            assert result.returncode == 0
            assert "[OK] Index rebuilt" in result.stdout


class TestCLI:
    def test_dry_run_prints_content_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "skills/obsidian/obsidian_writer.py",
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
                cwd="D:/AI/claude_code/claude-obsidian",
            )
            assert result.returncode == 0
            assert "RAG" in result.stdout
            assert "[DRY RUN]" in result.stdout

    def test_write_mode_outputs_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "skills/obsidian/obsidian_writer.py",
                    "--type", "topic",
                    "--title", "RAG",
                    "--fields", '{"主题说明": "overview", "当前结论": "retrieval improves grounding"}',
                    "--draft", "false",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd="D:/AI/claude_code/claude-obsidian",
            )
            assert result.returncode == 0
            assert "[OK] Written:" in result.stdout

    def test_write_mode_prints_topic_suggestion_when_no_topic_match_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "skills/obsidian/obsidian_writer.py",
                    "--type", "literature",
                    "--title", "Bitrate Control Survey",
                    "--fields", '{"核心观点": "x", "方法要点": "y"}',
                    "--draft", "false",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd="D:/AI/claude_code/claude-obsidian",
            )
            assert result.returncode == 0
            assert "[Topic suggestion]" in result.stdout
            assert "Topic - Bitrate Control" in result.stdout

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
                    "skills/obsidian/obsidian_writer.py",
                    "--type", "literature",
                    "--title", "Attention Survey",
                    "--fields", '{"核心观点": "x", "方法要点": "y"}',
                    "--draft", "false",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd="D:/AI/claude_code/claude-obsidian",
            )
            assert result.returncode == 0
            assert "[Link suggestions]" in result.stdout
            assert "[Topic suggestion]" not in result.stdout

    def test_write_mode_does_not_suggest_topic_for_topic_note_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "skills/obsidian/obsidian_writer.py",
                    "--type", "topic",
                    "--title", "RAG",
                    "--fields", '{"涓婚璇存槑": "overview", "褰撳墠缁撹": "retrieval improves grounding"}',
                    "--draft", "false",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd="D:/AI/claude_code/claude-obsidian",
            )
            assert result.returncode == 0
            assert "[Topic suggestion]" not in result.stdout

    def test_fleeting_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "skills/obsidian/obsidian_writer.py",
                    "--type", "fleeting",
                    "--fields", '{"content": "测试想法", "tags": "#test"}',
                    "--vault", tmp,
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd="D:/AI/claude_code/claude-obsidian",
            )
            assert result.returncode == 0
            assert "[DRY RUN]" in result.stdout
            assert "测试想法" in result.stdout

    def test_fleeting_missing_content_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "skills/obsidian/obsidian_writer.py",
                    "--type", "fleeting",
                    "--fields", '{}',
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd="D:/AI/claude_code/claude-obsidian",
            )
            assert result.returncode != 0
