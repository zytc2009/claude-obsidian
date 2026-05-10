"""Tests for skills.obsidian.frontmatter."""

from __future__ import annotations

import pytest

from skills.obsidian import frontmatter as fm


class TestParse:
    def test_parses_basic_frontmatter(self) -> None:
        text = "---\ntitle: Foo\nstatus: draft\n---\nbody here\n"
        result, body = fm.parse(text)
        assert result == {"title": "Foo", "status": "draft"}
        assert body == "body here\n"

    def test_no_frontmatter_returns_empty_and_full_text(self) -> None:
        text = "no frontmatter here"
        result, body = fm.parse(text)
        assert result == {}
        assert body == text

    def test_unterminated_frontmatter_returns_empty(self) -> None:
        text = "---\ntitle: Foo\nno close fence"
        result, body = fm.parse(text)
        assert result == {}
        assert body == text

    def test_empty_frontmatter(self) -> None:
        text = "---\n---\nbody\n"
        result, body = fm.parse(text)
        assert result == {}
        assert body == "body\n"

    def test_parse_dict_shim(self) -> None:
        text = "---\nk: v\n---\nbody"
        assert fm.parse_dict(text) == {"k": "v"}


class TestUpdateField:
    def test_inserts_missing_field(self) -> None:
        text = "---\ntitle: Foo\n---\nbody\n"
        out = fm.update_field(text, "status", "active")
        assert "status: active" in out
        assert "title: Foo" in out
        assert out.endswith("body\n")

    def test_updates_existing_field(self) -> None:
        text = "---\nstatus: draft\n---\nbody\n"
        out = fm.update_field(text, "status", "active")
        assert "status: active" in out
        assert "status: draft" not in out

    def test_no_op_when_no_frontmatter(self) -> None:
        text = "no frontmatter"
        assert fm.update_field(text, "k", "v") == text

    def test_read_field(self) -> None:
        text = "---\nstatus: active\n---\nbody"
        assert fm.read_field(text, "status") == "active"
        assert fm.read_field(text, "missing") == ""


class TestSections:
    def test_get_section_returns_body(self) -> None:
        text = "# Intro\nhello\n# Other\nstuff\n"
        assert fm.get_section(text, "Intro") == "hello"

    def test_get_section_missing_returns_empty(self) -> None:
        assert fm.get_section("# Other\n", "Missing") == ""

    def test_replace_existing_section(self) -> None:
        text = "# Intro\nold\n# Other\nkeep\n"
        out = fm.replace_section(text, "Intro", "new")
        assert "# Intro\nnew\n" in out
        assert "# Other\nkeep" in out

    def test_replace_nonexistent_section_appends(self) -> None:
        text = "# Other\nkeep\n"
        out = fm.replace_section(text, "New", "added")
        assert "# Other\nkeep" in out
        assert "# New\nadded\n" in out

    def test_replace_section_idempotent(self) -> None:
        text = "# Intro\nold\n# Other\nx\n"
        out1 = fm.replace_section(text, "Intro", "new")
        out2 = fm.replace_section(out1, "Intro", "new")
        assert out1 == out2

    def test_append_bullet_creates_section(self) -> None:
        text = "# Other\nx\n"
        out = fm.append_bullet_to_section(text, "# Sources", "ref")
        assert "# Sources\n- ref\n" in out

    def test_append_bullet_under_existing_section(self) -> None:
        text = "# Sources\n- a\n# Other\nx\n"
        out = fm.append_bullet_to_section(text, "# Sources", "b")
        assert "- a" in out and "- b" in out

    def test_append_bullet_idempotent(self) -> None:
        text = "# Sources\n- a\n"
        out = fm.append_bullet_to_section(text, "# Sources", "a")
        assert out == text


class TestWikilinks:
    def test_extracts_plain_links(self) -> None:
        assert fm.extract_wikilinks("see [[Foo]] and [[Bar]]") == {"Foo", "Bar"}

    def test_strips_folder_prefix(self) -> None:
        assert fm.extract_wikilinks("[[03-Knowledge/Topics/RAG]]") == {"RAG"}

    def test_alias_form_yields_stem(self) -> None:
        assert fm.extract_wikilinks("[[Foo|Display]]") == {"Foo"}

    def test_heading_fragment_yields_stem(self) -> None:
        assert fm.extract_wikilinks("[[Foo#Section]]") == {"Foo"}

    def test_with_alias_returns_pairs(self) -> None:
        out = fm.extract_wikilinks_with_alias("[[Foo]] [[Bar|baz]] [[Q#H]]")
        assert ("Foo", None) in out
        assert ("Bar", "baz") in out
        assert ("Q", None) in out

    def test_replace_target_simple(self) -> None:
        text = "see [[Old]]"
        out, count = fm.replace_wikilink_target(text, "Old", "New")
        assert out == "see [[New]]"
        assert count == 1

    def test_replace_target_preserves_alias(self) -> None:
        text = "[[Old|Display]]"
        out, count = fm.replace_wikilink_target(text, "Old", "New")
        assert out == "[[New|Display]]"
        assert count == 1

    def test_replace_target_preserves_heading(self) -> None:
        text = "[[Old#Section]]"
        out, count = fm.replace_wikilink_target(text, "Old", "New")
        assert out == "[[New#Section]]"
        assert count == 1

    def test_replace_target_preserves_folder(self) -> None:
        text = "[[notes/Old#H|Alias]]"
        out, count = fm.replace_wikilink_target(text, "Old", "New")
        assert out == "[[notes/New#H|Alias]]"

    def test_replace_target_skips_others(self) -> None:
        text = "[[Old]] and [[Other]]"
        out, count = fm.replace_wikilink_target(text, "Old", "New")
        assert out == "[[New]] and [[Other]]"
        assert count == 1

    def test_replace_target_count_multiple(self) -> None:
        text = "[[Old]] [[Old|x]] [[Old#h]]"
        _, count = fm.replace_wikilink_target(text, "Old", "New")
        assert count == 3


class TestAliases:
    def test_inline_list_form(self) -> None:
        assert fm.extract_aliases({"aliases": "[A, B, C]"}) == ["A", "B", "C"]

    def test_comma_separated(self) -> None:
        assert fm.extract_aliases({"aliases": "A, B"}) == ["A", "B"]

    def test_quoted_inline(self) -> None:
        assert fm.extract_aliases({"aliases": '["Foo Bar", Baz]'}) == ["Foo Bar", "Baz"]

    def test_empty(self) -> None:
        assert fm.extract_aliases({"aliases": ""}) == []
        assert fm.extract_aliases({}) == []

    def test_add_alias_to_doc_without_aliases(self) -> None:
        text = "---\ntitle: Foo\n---\nbody\n"
        out = fm.add_alias(text, "OldName")
        assert "aliases: [OldName]" in out

    def test_add_alias_appends_to_existing(self) -> None:
        text = "---\naliases: [A, B]\n---\nbody\n"
        out = fm.add_alias(text, "C")
        parsed = fm.extract_aliases(fm.parse_dict(out))
        assert parsed == ["A", "B", "C"]

    def test_add_alias_idempotent(self) -> None:
        text = "---\naliases: [A]\n---\n"
        out = fm.add_alias(text, "A")
        assert out == text
