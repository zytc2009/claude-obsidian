"""Tests for skills.obsidian.graph_view."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from skills.obsidian import graph_builder as gb
from skills.obsidian import graph_view as gv
from skills.obsidian import index as idx


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    for rel, _ in idx.INDEX_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    _write(root / "03-Knowledge/Topics/Topic - RAG.md",
           "---\nstatus: active\nupdated: 2026-05-10\n---\n## 主题说明\nthe rag topic\n## 重要资料\n[[Literature - WeKnora]]\n")
    _write(root / "03-Knowledge/Literature/Literature - WeKnora.md",
           '---\nstatus: active\nupdated: 2026-05-08\ntopic: ["Topic - RAG"]\nsource: https://example.com\n---\n## 核心观点\nimportant insight\n')
    return root


def test_render_creates_html_at_default_path(vault: Path) -> None:
    graph = gb.build_graph(vault)
    path = gv.render_html(graph, vault)
    assert path == vault / "_graph.html"
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_render_respects_custom_output_path(vault: Path, tmp_path: Path) -> None:
    graph = gb.build_graph(vault)
    target = tmp_path / "subdir" / "custom.html"
    path = gv.render_html(graph, vault, output=target)
    assert path == target
    assert target.exists()


def test_html_contains_required_elements(vault: Path) -> None:
    graph = gb.build_graph(vault)
    path = gv.render_html(graph, vault)
    html = path.read_text(encoding="utf-8")
    # Required structural elements
    assert 'id="info-panel"' in html
    assert 'id="viewport"' in html
    assert 'id="sidebar"' in html
    assert 'data-view="graph"' in html
    assert 'data-view="ego"' in html
    assert 'data-view="mindmap-topic"' in html
    assert 'data-view="health"' in html


def test_html_embeds_d3_with_sri_hash(vault: Path) -> None:
    graph = gb.build_graph(vault)
    html = gv.render_html(graph, vault).read_text(encoding="utf-8")
    assert "cdn.jsdelivr.net/npm/d3@" in html
    # SRI integrity attribute present
    assert re.search(r'integrity="sha384-[A-Za-z0-9+/=]+', html), "missing SRI hash"
    assert 'crossorigin="anonymous"' in html


def test_embedded_data_is_valid_json(vault: Path) -> None:
    graph = gb.build_graph(vault)
    html = gv.render_html(graph, vault).read_text(encoding="utf-8")
    m = re.search(r"const DATA = (\{.+?\});", html, flags=re.DOTALL)
    assert m, "DATA payload not found"
    data = json.loads(m.group(1))
    # Sanity checks on payload shape
    assert isinstance(data["nodes"], list) and data["nodes"]
    assert isinstance(data["edges"], list)
    assert "broken" in data and "topics" in data
    assert "health_tree" in data and "all_topic_mindmaps" in data
    assert data["stats"]["nodes"] == len(data["nodes"])
    # Health tree is well-formed (root with optional buckets)
    assert data["health_tree"]["type"] == "vault_root"
    assert isinstance(data["health_tree"]["children"], list)


def test_user_content_cannot_break_script_context(tmp_path: Path) -> None:
    """User-controlled content embedded inside the <script> tag must not
    be able to terminate the surrounding script via ``</script>``.

    Filenames are sanitised by the OS, so the realistic attack surface is
    frontmatter fields and section bodies. We assert the ``</`` sequence
    inside the data blob is escaped to ``<\\/`` (the canonical mitigation).
    """
    root = tmp_path / "vault"
    for rel, _ in idx.INDEX_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    payload = "</script><img src=x onerror=alert(1)>"
    _write(root / "03-Knowledge/Topics/Topic - X.md",
           f"---\nstatus: active\n---\n## 主题说明\n{payload}\n")
    graph = gb.build_graph(root)
    html = gv.render_html(graph, root).read_text(encoding="utf-8")
    # The dangerous closing tag in user data must be escaped so it can't
    # close the embedding <script>. We do NOT assert "payload not in html"
    # because the harmless suffix may pass through; the load-bearing
    # invariant is the closing-tag escape.
    assert "</script><img src=x onerror=alert(1)>" not in html
    assert "<\\/script>" in html


def test_default_topic_falls_back_to_highest_in_degree(vault: Path) -> None:
    # Add a more-linked topic so it becomes default
    _write(vault / "03-Knowledge/Topics/Topic - Hot.md",
           "---\nstatus: active\n---\n## X\nx\n")
    _write(vault / "03-Knowledge/Literature/Literature - One.md",
           "---\nstatus: active\n---\n## X\n[[Topic - Hot]]\n")
    _write(vault / "03-Knowledge/Literature/Literature - Two.md",
           "---\nstatus: active\n---\n## X\n[[Topic - Hot]]\n")
    graph = gb.build_graph(vault)
    html = gv.render_html(graph, vault).read_text(encoding="utf-8")
    m = re.search(r"const DATA = (\{.+?\});", html, flags=re.DOTALL)
    data = json.loads(m.group(1))
    assert data["default_topic"] == "Topic - Hot"


def test_initial_topic_override_honored(vault: Path) -> None:
    graph = gb.build_graph(vault)
    html = gv.render_html(graph, vault, initial_topic="Topic - RAG").read_text(encoding="utf-8")
    m = re.search(r"const DATA = (\{.+?\});", html, flags=re.DOTALL)
    data = json.loads(m.group(1))
    assert data["default_topic"] == "Topic - RAG"


def test_filter_type_propagates_to_data(vault: Path) -> None:
    graph = gb.build_graph(vault)
    html = gv.render_html(graph, vault, filter_type="literature").read_text(encoding="utf-8")
    m = re.search(r"const DATA = (\{.+?\});", html, flags=re.DOTALL)
    data = json.loads(m.group(1))
    assert data["filter_type"] == "literature"


def test_edge_helpers_and_clone_guard_present(vault: Path) -> None:
    """Regression: d3.forceLink mutates edge.source/target in place.

    The renderer must (a) read edge IDs via a helper that handles both
    string and object forms, and (b) clone DATA.edges before passing to
    forceLink so view switches don't end up with a corrupted shared
    edges array. The Ego and Graph views silently break otherwise:
    Ego shows only the centre node, Graph drops every edge on the
    second render. See conversation 2026-05-11.
    """
    graph = gb.build_graph(vault)
    html = gv.render_html(graph, vault).read_text(encoding="utf-8")
    # ID-reader helpers exist and handle both forms.
    assert "function edgeSourceId(e)" in html
    assert "function edgeTargetId(e)" in html
    assert 'typeof e.source === "object"' in html
    # cloneEdges shipped and used by both renderGraph and renderEgo.
    assert "function cloneEdges(edges)" in html
    # Both view functions clone edges before handing them to d3.forceLink.
    # We sanity-check by counting cloneEdges call sites.
    assert html.count("cloneEdges(") >= 2
