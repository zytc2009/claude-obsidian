"""Tests for skills.obsidian.graph_builder."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from skills.obsidian import graph_builder as gb
from skills.obsidian import index as idx


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    for rel, _ in idx.INDEX_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    (root / "00-Inbox").mkdir(parents=True, exist_ok=True)
    return root


def test_scans_managed_dirs_and_infers_type(vault: Path) -> None:
    _write(vault / "03-Knowledge/Topics/Topic - RAG.md",
           "---\nstatus: active\nupdated: 2026-05-10\n---\n## 主题说明\nx\n")
    _write(vault / "03-Knowledge/Literature/Literature - Foo.md",
           "---\nstatus: active\n---\n## 核心观点\ny\n")
    _write(vault / "03-Knowledge/Concepts/Concept - Bar.md",
           "---\nstatus: active\n---\n## 一句话定义\nz\n")
    _write(vault / "02-Projects/Project - P1.md",
           "---\nstatus: active\n---\n## 项目描述\nw\n")
    _write(vault / "03-Knowledge/MOCs/MOC - M1.md",
           "---\nstatus: active\n---\n## TOC\nq\n")
    _write(vault / "06-Articles/Article - A1.md",
           "---\nstatus: active\n---\n## 核心论点\nv\n")

    g = gb.build_graph(vault)
    by_type = {n.type for n in g.nodes}
    assert by_type == {"topic", "literature", "concept", "project", "moc", "article"}
    assert len(g.nodes) == 6


def test_excludes_drafts_by_default(vault: Path) -> None:
    _write(vault / "03-Knowledge/Topics/Topic - Draft.md",
           "---\nstatus: draft\n---\n## X\nx\n")
    _write(vault / "03-Knowledge/Topics/Topic - Active.md",
           "---\nstatus: active\n---\n## X\nx\n")
    g = gb.build_graph(vault)
    stems = {n.id for n in g.nodes}
    assert "Topic - Active" in stems
    assert "Topic - Draft" not in stems


def test_inbox_excluded_unless_opted_in(vault: Path) -> None:
    _write(vault / "00-Inbox/Note - Quick.md",
           "---\nstatus: active\n---\nbody\n")
    assert all(n.id != "Note - Quick" for n in gb.build_graph(vault).nodes)
    g = gb.build_graph(vault, include_inbox=True)
    inbox_nodes = [n for n in g.nodes if n.type == "inbox"]
    assert any(n.id == "Note - Quick" for n in inbox_nodes)


def test_extracts_explicit_wikilink_edges_with_section(vault: Path) -> None:
    _write(vault / "03-Knowledge/Topics/Topic - RAG.md",
           "---\nstatus: active\n---\n## 重要资料\n[[Literature - WeKnora]]\n")
    _write(vault / "03-Knowledge/Literature/Literature - WeKnora.md",
           "---\nstatus: active\n---\n## 核心观点\nx\n")
    g = gb.build_graph(vault)
    explicit = [e for e in g.edges if e.kind == "explicit"]
    assert any(
        e.source == "Topic - RAG" and e.target == "Literature - WeKnora"
        and e.section == "重要资料"
        for e in explicit
    )


def test_frontmatter_topic_is_implicit_edge(vault: Path) -> None:
    _write(vault / "03-Knowledge/Literature/Literature - X.md",
           '---\nstatus: active\ntopic: ["Topic - RAG", "Topic - LLM"]\n---\n## X\nx\n')
    _write(vault / "03-Knowledge/Topics/Topic - RAG.md",
           "---\nstatus: active\n---\n## X\nx\n")
    g = gb.build_graph(vault)
    implicit = [e for e in g.edges if e.kind == "implicit"]
    assert any(
        e.source == "Literature - X" and e.target == "Topic - RAG"
        and e.section == "_frontmatter"
        for e in implicit
    )
    # Topic - LLM is referenced but doesn't exist → broken
    assert "Topic - LLM" in g.broken


def test_broken_link_identification(vault: Path) -> None:
    _write(vault / "03-Knowledge/Topics/Topic - Real.md",
           "---\nstatus: active\n---\n## links\n[[Topic - Ghost]] [[Literature - Real]]\n")
    _write(vault / "03-Knowledge/Literature/Literature - Real.md",
           "---\nstatus: active\n---\n## x\nx\n")
    g = gb.build_graph(vault)
    assert "Topic - Ghost" in g.broken
    assert "Literature - Real" not in g.broken


def test_backlinks_and_forwardlinks_by_section(vault: Path) -> None:
    _write(vault / "03-Knowledge/Topics/Topic - Hub.md",
           "---\nstatus: active\n---\n## 重要资料\n[[Literature - A]]\n[[Literature - B]]\n## 知识连接\n[[Literature - A]]\n")
    _write(vault / "03-Knowledge/Literature/Literature - A.md",
           "---\nstatus: active\n---\n## x\nx\n")
    _write(vault / "03-Knowledge/Literature/Literature - B.md",
           "---\nstatus: active\n---\n## x\nx\n")
    g = gb.build_graph(vault)
    hub = next(n for n in g.nodes if n.id == "Topic - Hub")
    # forwardlinks_by_section: 重要资料 has 2 (A, B), 知识连接 has 1 (A)
    assert set(hub.forwardlinks_by_section.keys()) == {"重要资料", "知识连接"}
    assert sorted(hub.forwardlinks_by_section["重要资料"]) == [
        "Literature - A", "Literature - B"
    ]
    assert hub.forwardlinks_by_section["知识连接"] == ["Literature - A"]
    # backlinks on A include two from Hub: 重要资料 + 知识连接
    a = next(n for n in g.nodes if n.id == "Literature - A")
    sections_pointing_at_a = {bl["section"] for bl in a.backlinks}
    assert {"重要资料", "知识连接"} <= sections_pointing_at_a
    assert a.in_degree == 2  # two distinct edges from Hub


def test_section_content_truncated_to_cap(vault: Path) -> None:
    long_text = "x" * (gb.SECTION_CONTENT_CAP + 200)
    _write(vault / "03-Knowledge/Literature/Literature - Long.md",
           f"---\nstatus: active\n---\n## 核心观点\n{long_text}\n")
    g = gb.build_graph(vault)
    n = next(n for n in g.nodes if n.id == "Literature - Long")
    content = n.section_contents["核心观点"]
    assert len(content) <= gb.SECTION_CONTENT_CAP + 1  # +1 for the trailing ellipsis
    assert content.endswith("…")


def test_underscore_placeholder_sections_dropped(vault: Path) -> None:
    _write(vault / "03-Knowledge/Topics/Topic - Empty.md",
           "---\nstatus: active\n---\n## 主题说明\n_待补充_\n## 当前结论\nfilled in\n")
    g = gb.build_graph(vault)
    n = next(n for n in g.nodes if n.id == "Topic - Empty")
    assert "主题说明" not in n.section_contents
    assert n.section_contents["当前结论"] == "filled in"


def test_summary_falls_back_to_section_content(vault: Path) -> None:
    _write(vault / "03-Knowledge/Literature/Literature - Sum.md",
           "---\nstatus: active\n---\n## 解决的问题\nThis solves X for Y users.\n")
    g = gb.build_graph(vault)
    n = next(n for n in g.nodes if n.id == "Literature - Sum")
    assert n.summary.startswith("This solves X")


def test_self_links_are_ignored(vault: Path) -> None:
    _write(vault / "03-Knowledge/Topics/Topic - Self.md",
           "---\nstatus: active\n---\n## x\n[[Topic - Self]]\n")
    g = gb.build_graph(vault)
    n = next(n for n in g.nodes if n.id == "Topic - Self")
    assert n.in_degree == 0
    assert n.out_degree == 0


def test_stats_summary(vault: Path) -> None:
    _write(vault / "03-Knowledge/Topics/Topic - A.md",
           "---\nstatus: active\n---\n## x\n[[B]]\n")
    g = gb.build_graph(vault)
    s = g.stats()
    assert s["nodes"] == 1
    assert s["explicit"] == 1
    assert s["broken"] == 1
    assert s["edges"] == s["explicit"] + s["implicit"]


def test_topic_mindmap_builds_from_sections(vault: Path) -> None:
    _write(vault / "03-Knowledge/Topics/Topic - Hub.md",
           "---\nstatus: active\n---\n## 重要资料\n[[Literature - A]]\n## 当前结论\nDone.\n")
    _write(vault / "03-Knowledge/Literature/Literature - A.md",
           "---\nstatus: active\n---\n## x\nx\n")
    g = gb.build_graph(vault)
    mm = gb.build_topic_mindmap(vault, "Topic - Hub", g)
    assert mm["type"] == "topic_root"
    section_names = [c["name"] for c in mm["children"]]
    assert "重要资料" in section_names
    important = next(c for c in mm["children"] if c["name"] == "重要资料")
    assert any(leaf["name"] == "Literature - A" for leaf in important["children"])


def test_scan_drafts_returns_only_draft_status(vault: Path) -> None:
    _write(vault / "03-Knowledge/Topics/Topic - WIP.md",
           "---\nstatus: draft\nupdated: 2026-01-01\n---\n## 主题说明\nwork in progress\n")
    _write(vault / "03-Knowledge/Topics/Topic - Done.md",
           "---\nstatus: active\n---\n## X\nx\n")
    drafts = gb.scan_drafts(vault)
    assert len(drafts) == 1
    assert drafts[0].id == "Topic - WIP"
    assert drafts[0].type == "topic"
    assert drafts[0].updated == "2026-01-01"
    assert "work in progress" in drafts[0].summary


def test_health_tree_orphan_bucket(vault: Path) -> None:
    """A note with zero in/out edges lands in 🔴 孤儿."""
    _write(vault / "03-Knowledge/Literature/Literature - Alone.md",
           "---\nstatus: active\nupdated: 2026-05-10\n---\n## 核心观点\nbody\n")
    _write(vault / "03-Knowledge/Topics/Topic - Hub.md",
           "---\nstatus: active\nupdated: 2026-05-10\n---\n## 重要资料\n[[Literature - X]]\n")
    g = gb.build_graph(vault)
    health = gb.build_health_tree(g, [], today=date(2026, 5, 11))
    orphan_buckets = [c for c in health["children"] if c["type"] == "health_orphan"]
    assert orphan_buckets, "expected an orphan bucket"
    orphan_stems = {child["name"] for child in orphan_buckets[0]["children"]}
    assert "Literature - Alone" in orphan_stems
    # Hub has out-degree > 0 (even though target is broken), so not an orphan
    assert "Topic - Hub" not in orphan_stems


def test_health_tree_broken_bucket(vault: Path) -> None:
    _write(vault / "03-Knowledge/Topics/Topic - Linker.md",
           "---\nstatus: active\nupdated: 2026-05-10\n---\n"
           "## 重要资料\n[[Literature - Ghost]] [[Literature - Real]]\n")
    _write(vault / "03-Knowledge/Literature/Literature - Real.md",
           "---\nstatus: active\nupdated: 2026-05-10\n---\n## X\nx\n")
    g = gb.build_graph(vault)
    health = gb.build_health_tree(g, [], today=date(2026, 5, 11))
    broken_buckets = [c for c in health["children"] if c["type"] == "health_broken"]
    assert broken_buckets, "expected a broken-link bucket"
    broken_stems = {child["name"] for child in broken_buckets[0]["children"]}
    assert "Topic - Linker" in broken_stems


def test_health_tree_stale_bucket_threshold(vault: Path) -> None:
    today = date(2026, 5, 11)
    fresh_date = (today - timedelta(days=10)).isoformat()
    stale_date = (today - timedelta(days=gb.STALE_THRESHOLD_DAYS + 1)).isoformat()
    _write(vault / "03-Knowledge/Topics/Topic - Fresh.md",
           f"---\nstatus: active\nupdated: {fresh_date}\n---\n## X\nx\n")
    _write(vault / "03-Knowledge/Topics/Topic - Stale.md",
           f"---\nstatus: active\nupdated: {stale_date}\n---\n## X\nx\n")
    g = gb.build_graph(vault)
    health = gb.build_health_tree(g, [], today=today)
    stale_buckets = [c for c in health["children"] if c["type"] == "health_stale"]
    assert stale_buckets, "expected a stale bucket"
    stale_stems = {child["name"] for child in stale_buckets[0]["children"]}
    assert "Topic - Stale" in stale_stems
    assert "Topic - Fresh" not in stale_stems


def test_health_tree_shell_bucket(vault: Path) -> None:
    """Notes where every section is ``_待补充_`` end up empty after
    truncation and should be flagged as shells."""
    today = date(2026, 5, 11)
    fresh = (today - timedelta(days=5)).isoformat()
    _write(vault / "03-Knowledge/Topics/Topic - Shell.md",
           f"---\nstatus: active\nupdated: {fresh}\n---\n"
           "## 主题说明\n_待补充_\n## 当前结论\n_待补充_\n")
    _write(vault / "03-Knowledge/Topics/Topic - Filled.md",
           f"---\nstatus: active\nupdated: {fresh}\n---\n## 主题说明\nreal content\n")
    g = gb.build_graph(vault)
    health = gb.build_health_tree(g, [], today=today)
    shell_buckets = [c for c in health["children"] if c["type"] == "health_shell"]
    assert shell_buckets, "expected a shell bucket"
    shell_stems = {child["name"] for child in shell_buckets[0]["children"]}
    assert "Topic - Shell" in shell_stems
    assert "Topic - Filled" not in shell_stems


def test_health_tree_draft_bucket(vault: Path) -> None:
    """Drafts are excluded from graph topology but surface in the
    health tree via the separately-collected ``drafts`` arg."""
    drafts = [
        gb.DraftNote(id="Topic - WIP", type="topic",
                     summary="ideas", updated="2026-04-01",
                     rel_path="03-Knowledge/Topics/Topic - WIP.md"),
    ]
    g = gb.VaultGraph(nodes=[], edges=[], broken=[], topics=[])
    health = gb.build_health_tree(g, drafts, today=date(2026, 5, 11))
    draft_buckets = [c for c in health["children"] if c["type"] == "health_draft"]
    assert draft_buckets, "expected a draft bucket"
    assert {c["name"] for c in draft_buckets[0]["children"]} == {"Topic - WIP"}


def test_health_tree_omits_empty_buckets(vault: Path) -> None:
    """A perfectly healthy vault produces an empty root, not buckets
    full of zero items."""
    today = date(2026, 5, 11)
    fresh = today.isoformat()
    _write(vault / "03-Knowledge/Topics/Topic - A.md",
           f"---\nstatus: active\nupdated: {fresh}\n---\n## 主题说明\nfilled\n[[Topic - B]]\n")
    _write(vault / "03-Knowledge/Topics/Topic - B.md",
           f"---\nstatus: active\nupdated: {fresh}\n---\n## 主题说明\nfilled\n[[Topic - A]]\n")
    g = gb.build_graph(vault)
    health = gb.build_health_tree(g, [], today=today)
    # Linked, fresh, filled, no drafts → all five buckets should be empty.
    assert health["children"] == []


def test_is_stale_handles_missing_and_malformed_dates() -> None:
    today = date(2026, 5, 11)
    assert gb._is_stale("", today=today) is True  # missing → stale
    assert gb._is_stale("not-a-date", today=today) is True  # garbled → stale
    assert gb._is_stale("2026-05-01", today=today) is False
    assert gb._is_stale("2024-01-01", today=today) is True
