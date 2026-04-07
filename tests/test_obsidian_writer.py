import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

import pytest

from skills.obsidian.obsidian_writer import (
    NOTE_CONFIG,
    append_fleeting,
    get_target_path,
    is_draft_by_content,
    make_filename,
    render_concept,
    render_literature,
    render_project,
    render_topic,
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

    def test_fills_placeholder_for_empty_field(self):
        result = render_literature("Test", {})
        assert "_待补充_" in result

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

    def test_fills_placeholder_for_empty_field(self):
        result = render_concept("Test", {})
        assert "_待补充_" in result

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

    def test_fills_placeholder_for_empty_field(self):
        result = render_topic("Test", {})
        assert "_待补充_" in result

    def test_frontmatter_type_is_topic(self):
        result = render_topic("Test", {})
        assert "type: topic" in result


class TestRenderProject:
    def test_includes_title_in_output(self):
        result = render_project("本地知识库搭建", {})
        assert "本地知识库搭建" in result

    def test_fills_provided_field(self):
        fields = {"项目目标": "Build local RAG demo"}
        result = render_project("Test", fields)
        assert "Build local RAG demo" in result

    def test_fills_placeholder_for_empty_field(self):
        result = render_project("Test", {})
        assert "_待补充_" in result

    def test_frontmatter_type_is_project(self):
        result = render_project("Test", {})
        assert "type: project" in result

    def test_includes_experiment_section(self):
        result = render_project("Test", {})
        assert "实验记录" in result


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
                              title="RAG", fields={"主题说明": "x", "核心概念": "y"},
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
                    "--fields", '{"主题说明": "overview", "核心概念": "retrieval"}',
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
