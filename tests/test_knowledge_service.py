"""Smoke tests for skills.obsidian.knowledge_service.

Most behavior is already exercised through obsidian_writer's CLI tests;
these direct tests pin the helper-level contracts in case obsidian_writer
is later removed.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from skills.obsidian import knowledge_service as ks


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    for d in [
        "00-Inbox",
        "02-Projects",
        "03-Knowledge/Topics",
        "03-Knowledge/Concepts",
        "03-Knowledge/Literature",
        "03-Knowledge/MOCs",
        "06-Articles",
    ]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestQueryKeywords:
    def test_falls_back_to_short_tokens(self) -> None:
        # All-stop-word phrase yields nothing from suggestion_keywords;
        # fallback splits on whitespace and keeps tokens >= 2 chars.
        kws = ks.query_keywords("the of")
        # Both "the" and "of" pass length>=2 fallback.
        assert "the" in kws or "of" in kws


class TestProfileSection:
    def test_extracts_named_block(self) -> None:
        profile = "## 编程语言\nPython, Go\n## 工具链\nVS Code, Docker\n"
        assert ks.extract_profile_section(profile, "编程语言") == "Python, Go"

    def test_missing_section_returns_empty(self) -> None:
        assert ks.extract_profile_section("# Other\n", "编程语言") == ""


class TestTopicSummaryPayload:
    def test_extracts_three_canonical_sections(self, vault: Path) -> None:
        text = (
            "---\n---\n"
            "# 主题说明\nWhat it is\n"
            "# 当前结论\nKey conclusion\n"
            "# 未解决问题\nWhat to study next\n"
        )
        path = vault / "03-Knowledge/Topics/Topic - X.md"
        path.write_text(text, encoding="utf-8")
        payload = ks.topic_summary_payload(path, text)
        assert payload["title"] == "Topic - X"
        assert payload["主题说明"] == "What it is"
        assert payload["当前结论"] == "Key conclusion"
        assert payload["未解决问题"] == "What to study next"


# ---------------------------------------------------------------------------
# query_vault — high-level
# ---------------------------------------------------------------------------


class TestQueryVault:
    def test_returns_topic_match_in_tier1(self, vault: Path) -> None:
        _write(
            vault / "03-Knowledge/Topics/Topic - RAG.md",
            "---\n---\n# 主题说明\nretrieval augmented generation\n",
        )
        result = ks.query_vault(vault, "retrieval", limit=5)
        titles = [t["title"] for t in result["tier1_topics"]]
        assert "Topic - RAG" in titles

    def test_no_match_returns_empty_lists(self, vault: Path) -> None:
        result = ks.query_vault(vault, "nothing in this empty vault")
        assert result["tier1_topics"] == []
        assert result["tier2_grouped"] == []


# ---------------------------------------------------------------------------
# fix_frontmatter — pure
# ---------------------------------------------------------------------------


class TestFixFrontmatter:
    def test_inserts_missing_fields(self) -> None:
        text = "---\ntype: literature\n---\nbody"
        new_text, fixes = ks.fix_frontmatter(text, Path("a.md"), {"type": "literature"})
        assert "status: active" in new_text
        assert "created:" in new_text
        assert fixes  # non-empty fix log

    def test_no_op_when_complete(self) -> None:
        text = "---\nstatus: active\ncreated: 2026-01-01\nupdated: 2026-01-01\nreviewed: false\n---"
        fmd = {
            "status": "active",
            "created": "2026-01-01",
            "updated": "2026-01-01",
            "reviewed": "false",
        }
        new_text, fixes = ks.fix_frontmatter(text, Path("a.md"), fmd)
        assert new_text == text
        assert fixes == []


# ---------------------------------------------------------------------------
# lint_vault — smoke
# ---------------------------------------------------------------------------


class TestLintVault:
    def test_runs_without_errors_on_empty_vault(self, vault: Path, capsys) -> None:
        ks.lint_vault(vault)
        out = capsys.readouterr().out
        assert "[Lint] Scanned" in out

    def test_detects_broken_link(self, vault: Path, capsys) -> None:
        _write(vault / "03-Knowledge/Concepts/Concept - X.md", "see [[Missing Note]]\n")
        ks.lint_vault(vault)
        out = capsys.readouterr().out
        assert "Broken links" in out
        assert "Missing Note" in out

    def test_detects_inbox_backlog(self, vault: Path, capsys) -> None:
        old_date = (date.today() - timedelta(days=10)).isoformat()
        _write(
            vault / "00-Inbox/Concept - Old.md",
            f"---\ncreated: {old_date}\n---\nbody\n",
        )
        ks.lint_vault(vault)
        out = capsys.readouterr().out
        assert "Inbox backlog" in out

    def test_auto_fix_inserts_frontmatter(self, vault: Path) -> None:
        path = vault / "03-Knowledge/Concepts/Concept - X.md"
        _write(path, "---\ntype: concept\n---\nbody\n")
        ks.lint_vault(vault, auto_fix=True)
        text = path.read_text(encoding="utf-8")
        assert "status: active" in text
        assert "created:" in text
