"""
graph_view.py — Render a :class:`VaultGraph` to a self-contained HTML file.

Embeds the graph data as JSON and a D3.js force-directed viewer
(CDN-loaded with SRI hash so the rendered file remains tamper-evident).
The output is a single HTML — no external assets are written.

Four views are wired in the same file:
  * Graph     — full force-directed network
  * Ego       — single topic at the centre with one-hop neighbours
  * Mindmap (topic)  — radial tree rooted at a topic, branches by H2
  * Mindmap (vault)  — radial tree rooted at the vault, grouped by type

Interaction:
  * Hover     — highlight neighbours only (no tooltip)
  * Click     — open a persistent right-side info panel
  * Esc / ✕   — close the panel
  * Buttons   — open in Obsidian, copy wikilink, jump to source URL
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

try:
    from .graph_builder import (
        VaultGraph,
        build_health_tree,
        build_topic_mindmap,
        scan_drafts,
    )
except ImportError:  # script-mode fallback
    from graph_builder import (  # type: ignore[no-redef]
        VaultGraph,
        build_health_tree,
        build_topic_mindmap,
        scan_drafts,
    )


__all__ = ["render_html"]


# D3 v7.9.0 — pinned with subresource integrity. If you bump the version
# the SRI hash MUST be regenerated, otherwise the script tag will fail
# to load and the viewer will silently break.
#
# Regenerate via:
#   python -c "import urllib.request,hashlib,base64; \
#     data=urllib.request.urlopen('<URL>').read(); \
#     print('sha384-'+base64.b64encode(hashlib.sha384(data).digest()).decode())"
_D3_URL = "https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"
_D3_INTEGRITY = (
    "sha384-CjloA8y00+1SDAUkjs099PVfnY2KmDC2BZnws9kh8D/lX1s46w6EPhpXdqMfjK6i"
)


def render_html(
    graph: VaultGraph,
    vault: Path,
    *,
    output: Path | None = None,
    filter_type: str = "",
    initial_topic: str = "",
) -> Path:
    """Render ``graph`` to a single HTML file. Returns the output path.

    :param graph: scanned vault graph (see :mod:`graph_builder`).
    :param vault: vault root (used for the ``obsidian://`` deep link).
    :param output: target path; defaults to ``<vault>/_graph.html``.
    :param filter_type: pre-select only this node type in the filter UI
        (still mutable from the sidebar).
    :param initial_topic: stem of the topic to land on for ego/mindmap
        views. Falls back to the highest-in-degree topic.
    """

    if output is None:
        output = vault / "_graph.html"

    # Pre-compute mindmaps for every topic so the picker is instant
    all_topic_mindmaps: dict[str, Any] = {}
    for stem in graph.topics:
        try:
            all_topic_mindmaps[stem] = build_topic_mindmap(vault, stem, graph)
        except Exception:
            # A single broken mindmap should not break the whole viewer
            all_topic_mindmaps[stem] = {
                "name": stem, "type": "topic_root", "children": []
            }

    # Default topic = highest in-degree topic
    if not initial_topic:
        topic_by_indeg = sorted(
            (n for n in graph.nodes if n.type == "topic"),
            key=lambda n: -n.in_degree,
        )
        if topic_by_indeg:
            initial_topic = topic_by_indeg[0].id

    drafts = scan_drafts(vault)
    health_tree = build_health_tree(graph, drafts)

    data = {
        "nodes": [asdict(n) for n in graph.nodes],
        "edges": [asdict(e) for e in graph.edges],
        "broken": graph.broken,
        "topics": graph.topics,
        "health_tree": health_tree,
        "all_topic_mindmaps": all_topic_mindmaps,
        "default_topic": initial_topic,
        "vault_path": str(vault).replace("\\", "/"),
        "filter_type": filter_type,
        "stats": graph.stats(),
        "drafts_count": len(drafts),
    }

    # When embedding JSON inside a <script> block, ``</script>`` in the
    # data would prematurely close the surrounding tag and expose us to
    # script injection. The canonical fix is to escape ``</`` and ``<!``
    # so they cannot terminate the script context. We also leave `` ``
    # / `` `` as JSON-escaped (json.dumps does this by default with
    # ensure_ascii=False only for non-string controls; we force it).
    raw_json = json.dumps(data, ensure_ascii=False)
    safe_json = (
        raw_json.replace("</", "<\\/").replace("<!--", "<\\!--")
        .replace(" ", "\\u2028").replace(" ", "\\u2029")
    )
    html = _TEMPLATE.replace(
        "__DATA_JSON__", safe_json
    ).replace(
        "__D3_URL__", _D3_URL
    ).replace(
        "__D3_INTEGRITY__", _D3_INTEGRITY
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


# ---------------------------------------------------------------------------
# HTML template — single file, embeds CDN-loaded D3 + JSON data.
# ---------------------------------------------------------------------------

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>知识图谱 · claude-obsidian</title>
<script src="__D3_URL__"
        integrity="__D3_INTEGRITY__"
        crossorigin="anonymous"></script>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, "Microsoft YaHei", "Segoe UI", sans-serif;
         background: #FAFAFA; color: #1F2937; overflow: hidden; }
  #app { display: grid; grid-template-columns: 260px 1fr; height: 100vh;
         transition: grid-template-columns 0.2s ease; }
  #app.with-panel { grid-template-columns: 260px 1fr 420px; }
  /* Sidebar */
  #sidebar { background: white; border-right: 1px solid #E5E7EB; padding: 18px;
             overflow-y: auto; }
  #sidebar h1 { font-size: 16px; margin: 0 0 4px; color: #111827; }
  #sidebar .subtitle { font-size: 11px; color: #6B7280; margin-bottom: 18px; }
  .section { margin-bottom: 22px; }
  .section h2 { font-size: 11px; font-weight: 600; color: #6B7280; text-transform: uppercase;
                margin: 0 0 8px; letter-spacing: 0.05em; }
  .view-btn { display: block; width: 100%; text-align: left; padding: 8px 12px;
              border: 1px solid #E5E7EB; background: white; border-radius: 8px;
              margin-bottom: 6px; cursor: pointer; font-size: 13px; color: #374151;
              transition: all 0.15s; }
  .view-btn:hover { border-color: #9CA3AF; background: #F9FAFB; }
  .view-btn.active { background: #1F2937; color: white; border-color: #1F2937; }
  .filter-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px;
                font-size: 12px; cursor: pointer; padding: 4px 6px; border-radius: 4px; }
  .filter-row:hover { background: #F3F4F6; }
  .dot { width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; }
  .filter-row input { margin: 0; }
  .count { margin-left: auto; color: #9CA3AF; font-size: 11px; font-variant-numeric: tabular-nums; }
  select, input[type="search"] { width: 100%; padding: 6px 8px; font-size: 12px;
              border: 1px solid #D1D5DB; border-radius: 6px; background: white; }
  .stats { font-size: 11px; color: #6B7280; line-height: 1.7; }
  .stats strong { color: #1F2937; font-variant-numeric: tabular-nums; }
  /* Main */
  #main { position: relative; min-width: 0; }
  #viewport { width: 100%; height: 100vh; }
  /* Right info panel */
  #info-panel { background: white; border-left: 1px solid #E5E7EB;
                display: none; flex-direction: column; height: 100vh; overflow: hidden; }
  #app.with-panel #info-panel { display: flex; }
  .ip-header { padding: 18px 20px 14px; border-bottom: 1px solid #F3F4F6;
               position: relative; flex-shrink: 0; }
  .ip-close { position: absolute; top: 14px; right: 14px; background: transparent;
              border: none; cursor: pointer; padding: 4px 8px; border-radius: 4px;
              color: #6B7280; font-size: 16px; }
  .ip-close:hover { background: #F3F4F6; color: #1F2937; }
  .ip-title { font-size: 16px; font-weight: 700; color: #111827;
              line-height: 1.35; word-break: break-word; padding-right: 32px; }
  .ip-chips { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; align-items: center; }
  .ip-chip { font-size: 10px; padding: 2px 9px; border-radius: 10px;
             font-weight: 500; line-height: 1.6; white-space: nowrap; }
  .ip-chip-type { color: white; }
  .ip-chip-meta { background: #F3F4F6; color: #4B5563; }
  .ip-chip-tag { background: #FEF3C7; color: #92400E; }
  .ip-chip-broken { background: #FEE2E2; color: #B91C1C; }
  .ip-actions { display: flex; gap: 6px; margin-top: 12px; flex-wrap: wrap; }
  .ip-btn { font-size: 11px; padding: 6px 10px; border: 1px solid #D1D5DB;
            background: white; border-radius: 6px; cursor: pointer; color: #374151;
            display: inline-flex; align-items: center; gap: 4px; }
  .ip-btn:hover { background: #F9FAFB; border-color: #9CA3AF; }
  .ip-btn-primary { background: #1F2937; color: white; border-color: #1F2937; }
  .ip-btn-primary:hover { background: #111827; color: white; }
  .ip-body { padding: 14px 20px 24px; overflow-y: auto; flex: 1; }
  .ip-summary { font-size: 13px; color: #374151; line-height: 1.6;
                margin-bottom: 18px; padding: 10px 12px;
                background: #F9FAFB; border-radius: 6px;
                border-left: 3px solid #E5E7EB; }
  .ip-section { margin-bottom: 18px; }
  .ip-section-label { font-size: 10px; color: #6B7280; font-weight: 600;
                      text-transform: uppercase; letter-spacing: 0.06em;
                      margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
  .ip-section-label .count { background: #F3F4F6; color: #4B5563; padding: 1px 6px;
                             border-radius: 8px; font-size: 9px; }
  .ip-key-field { background: #FFFBEB; border: 1px solid #FDE68A; border-radius: 6px;
                  padding: 10px 12px; margin-bottom: 8px; }
  .ip-key-field-name { font-size: 10px; font-weight: 600; color: #92400E;
                       text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
  .ip-key-field-content { font-size: 12px; color: #1F2937; line-height: 1.55;
                          white-space: pre-wrap; word-break: break-word; }
  details.ip-section-detail { border-top: 1px solid #F3F4F6; padding-top: 10px;
                              margin-top: 8px; }
  details.ip-section-detail summary { cursor: pointer; font-size: 11px;
                                      color: #4B5563; font-weight: 500; padding: 4px 0; }
  details.ip-section-detail summary:hover { color: #1F2937; }
  details.ip-section-detail[open] summary { color: #1F2937; margin-bottom: 8px; }
  .ip-link-row { font-size: 12px; color: #374151; padding: 6px 8px;
                 border-radius: 4px; cursor: pointer; display: flex;
                 align-items: center; gap: 8px; line-height: 1.5; }
  .ip-link-row:hover { background: #F3F4F6; }
  .ip-link-row .arrow { color: #9CA3AF; font-size: 10px; flex-shrink: 0; }
  .ip-link-row .src { flex: 1; word-break: break-word; }
  .ip-link-row .sec { color: #9CA3AF; font-size: 10px; flex-shrink: 0; }
  .ip-fwd-row { font-size: 12px; color: #374151; line-height: 1.7;
                display: flex; align-items: center; gap: 8px; padding: 2px 8px; }
  .ip-fwd-row .sec-name { color: #6B7280; font-weight: 500; flex: 1; }
  .ip-fwd-row .count-badge { background: #DBEAFE; color: #1D4ED8;
                             padding: 1px 8px; border-radius: 10px; font-size: 11px;
                             font-weight: 600; font-variant-numeric: tabular-nums; }
  .ip-source-link { font-size: 11px; color: #2563EB; text-decoration: none;
                    word-break: break-all; }
  .ip-source-link:hover { text-decoration: underline; }
  .ip-toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
              background: #1F2937; color: white; padding: 10px 18px; border-radius: 6px;
              font-size: 12px; opacity: 0; transition: opacity 0.2s; pointer-events: none;
              z-index: 2000; }
  .ip-toast.show { opacity: 1; }
  /* Health view (HTML, not SVG) */
  #health-viewport { display: none; width: 100%; height: 100vh; overflow-y: auto;
                     padding: 70px 32px 32px; background: #FAFAFA; }
  body.health-active #viewport { display: none; }
  body.health-active #health-viewport { display: block; }
  .health-wrap { max-width: 920px; margin: 0 auto; }
  .health-summary { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px;
                    margin-bottom: 28px; }
  .health-stat { background: white; border-radius: 10px; padding: 14px 16px;
                 border: 1px solid #E5E7EB;
                 box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
  .health-stat .count { font-size: 28px; font-weight: 700; line-height: 1;
                        font-variant-numeric: tabular-nums; }
  .health-stat .label { font-size: 11px; color: #6B7280; margin-top: 4px;
                        font-weight: 500; }
  .health-stat.empty .count { color: #D1D5DB; }
  .health-bucket { background: white; border-radius: 10px; margin-bottom: 14px;
                   border: 1px solid #E5E7EB; overflow: hidden; }
  .health-bucket-header { display: flex; align-items: center; gap: 12px;
                          padding: 14px 18px; cursor: pointer;
                          user-select: none; background: white;
                          border-bottom: 1px solid #F3F4F6; }
  .health-bucket-header:hover { background: #F9FAFB; }
  .health-bucket-header .chev { color: #9CA3AF; transition: transform 0.15s;
                                font-size: 12px; }
  .health-bucket.collapsed .chev { transform: rotate(-90deg); }
  .health-bucket.collapsed .health-bucket-body { display: none; }
  .health-bucket.collapsed .health-bucket-header { border-bottom: none; }
  .health-bucket-icon { font-size: 18px; }
  .health-bucket-title { font-weight: 600; font-size: 14px; color: #111827; flex: 1; }
  .health-bucket-count { background: #F3F4F6; color: #4B5563; padding: 2px 10px;
                         border-radius: 12px; font-size: 11px; font-weight: 600;
                         font-variant-numeric: tabular-nums; }
  .health-bucket-body { max-height: 360px; overflow-y: auto; }
  .health-item { display: flex; align-items: center; gap: 12px;
                 padding: 10px 18px; cursor: pointer;
                 border-top: 1px solid #F9FAFB; line-height: 1.5; }
  .health-item:first-child { border-top: none; }
  .health-item:hover { background: #F9FAFB; }
  .health-item .type-dot { width: 9px; height: 9px; border-radius: 50%;
                            flex-shrink: 0; }
  .health-item .title { font-size: 13px; color: #1F2937; font-weight: 500;
                        flex: 1; word-break: break-word; }
  .health-item .meta { font-size: 11px; color: #9CA3AF; flex-shrink: 0; }
  .health-empty { padding: 18px; text-align: center; color: #9CA3AF;
                  font-size: 12px; }
  .health-toolbar { display: flex; gap: 8px; justify-content: flex-end;
                    margin-bottom: 16px; }
  .health-toolbar button { padding: 5px 10px; font-size: 11px; border: 1px solid #D1D5DB;
                           background: white; border-radius: 6px; cursor: pointer;
                           color: #4B5563; }
  .health-toolbar button:hover { background: #F9FAFB; }
  .health-h1 { font-size: 22px; font-weight: 700; color: #111827; margin: 0 0 6px; }
  .health-sub { font-size: 13px; color: #6B7280; margin-bottom: 24px; }
  /* SVG */
  svg { background: #FAFAFA; }
  .node-circle { cursor: pointer; transition: stroke-width 0.15s; }
  .node-circle:hover { stroke-width: 4; }
  .node-label { font-size: 11px; fill: #1F2937; pointer-events: none;
                font-family: "Microsoft YaHei", sans-serif; }
  .link-explicit { stroke: #9CA3AF; stroke-opacity: 0.5; }
  .link-implicit { stroke: #CBD5E1; stroke-opacity: 0.5; stroke-dasharray: 3,3; }
  .link-highlight { stroke: #1F2937; stroke-opacity: 1; stroke-width: 2.5; }
  .node-dim { opacity: 0.15; }
  .mindmap-link { fill: none; stroke: #CBD5E1; stroke-width: 1.5; }
  /* Toolbar */
  #toolbar { position: absolute; top: 16px; right: 16px; background: white;
             padding: 6px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);
             display: flex; gap: 4px; }
  #toolbar button { padding: 6px 10px; border: none; background: transparent;
                    border-radius: 4px; cursor: pointer; font-size: 12px; color: #374151; }
  #toolbar button:hover { background: #F3F4F6; }
  #view-title { position: absolute; top: 16px; left: 16px; font-size: 13px;
                color: #6B7280; background: white; padding: 6px 12px; border-radius: 6px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.04); }
</style>
</head>
<body>
<div id="app">
  <aside id="sidebar">
    <h1>🌳 claude-obsidian</h1>
    <div class="subtitle">Knowledge Graph + Mindmap</div>

    <div class="section">
      <h2>View 视图</h2>
      <button class="view-btn active" data-view="graph">📊 Graph 全量力导向</button>
      <button class="view-btn" data-view="ego">🎯 Ego 单 topic 辐射</button>
      <button class="view-btn" data-view="mindmap-topic">🗺️ Mindmap 单 topic 导图</button>
      <button class="view-btn" data-view="health">🏥 Health 健康检查</button>
    </div>

    <div class="section" id="topic-picker-section" style="display:none">
      <h2>Topic 选择</h2>
      <select id="topic-picker"></select>
    </div>

    <div class="section" id="filter-section">
      <h2>Filter 类型过滤</h2>
      <label class="filter-row"><input type="checkbox" data-type="topic" checked>
        <span class="dot" style="background:#FB923C"></span> Topic <span class="count" data-count="topic">0</span></label>
      <label class="filter-row"><input type="checkbox" data-type="literature" checked>
        <span class="dot" style="background:#60A5FA"></span> Literature <span class="count" data-count="literature">0</span></label>
      <label class="filter-row"><input type="checkbox" data-type="project" checked>
        <span class="dot" style="background:#A78BFA"></span> Project <span class="count" data-count="project">0</span></label>
      <label class="filter-row"><input type="checkbox" data-type="concept" checked>
        <span class="dot" style="background:#34D399"></span> Concept <span class="count" data-count="concept">0</span></label>
      <label class="filter-row"><input type="checkbox" data-type="moc" checked>
        <span class="dot" style="background:#94A3B8"></span> MOC <span class="count" data-count="moc">0</span></label>
      <label class="filter-row"><input type="checkbox" data-type="article" checked>
        <span class="dot" style="background:#F87171"></span> Article <span class="count" data-count="article">0</span></label>
      <label class="filter-row"><input type="checkbox" data-type="inbox" checked>
        <span class="dot" style="background:#D1D5DB"></span> Inbox <span class="count" data-count="inbox">0</span></label>
    </div>

    <div class="section">
      <h2>Search 搜索</h2>
      <input type="search" id="search-input" placeholder="按标题搜索…">
    </div>

    <div class="section">
      <h2>Stats 统计</h2>
      <div class="stats" id="stats"></div>
    </div>

    <div class="section">
      <h2>Tips</h2>
      <div class="stats">
        · 点击节点 → 右侧详情<br>
        · 悬停高亮邻居<br>
        · 拖拽 / 滚轮缩放<br>
        · Esc 关闭面板
      </div>
    </div>
  </aside>

  <main id="main">
    <div id="view-title">Graph View</div>
    <div id="toolbar">
      <button id="btn-reset">↺ Reset</button>
      <button id="btn-zoomin">＋</button>
      <button id="btn-zoomout">－</button>
    </div>
    <svg id="viewport"></svg>
    <div id="health-viewport"></div>
  </main>

  <aside id="info-panel">
    <div class="ip-header">
      <button class="ip-close" title="关闭 (Esc)">✕</button>
      <div class="ip-title" id="ip-title">—</div>
      <div class="ip-chips" id="ip-chips"></div>
      <div class="ip-actions" id="ip-actions"></div>
    </div>
    <div class="ip-body" id="ip-body"></div>
  </aside>
</div>
<div class="ip-toast" id="ip-toast"></div>

<script>
const DATA = __DATA_JSON__;
const COLORS = {
  topic: "#FB923C", literature: "#60A5FA", concept: "#34D399",
  project: "#A78BFA", moc: "#94A3B8", article: "#F87171", inbox: "#D1D5DB",
  missing: "#FCA5A5", section: "#F59E0B", topic_root: "#1F2937",
  vault_root: "#1F2937", type_group: "#6B7280", prose: "#E5E7EB",
  // Health view buckets
  health_orphan: "#EF4444", health_broken: "#F97316",
  health_draft: "#A855F7", health_stale: "#EAB308", health_shell: "#6B7280",
};
const RINGS = {
  topic: "#EA580C", literature: "#2563EB", concept: "#059669",
  project: "#7C3AED", moc: "#475569", article: "#DC2626", inbox: "#9CA3AF",
  health_orphan: "#B91C1C", health_broken: "#C2410C",
  health_draft: "#7E22CE", health_stale: "#A16207", health_shell: "#374151",
};
const TYPE_LABELS = {
  topic: "主题页", literature: "资料", concept: "概念卡",
  project: "项目", moc: "索引", article: "文章", inbox: "Inbox",
  section: "区块", topic_root: "主题", vault_root: "Vault",
  type_group: "类型分组", prose: "正文", missing: "未找到",
};
const KEY_FIELDS = {
  topic: ["主题说明", "核心问题", "当前结论", "未解决问题"],
  literature: ["这份资料试图解决什么问题", "解决的问题", "核心观点", "方法要点"],
  concept: ["一句话定义", "核心机制", "适用场景", "我的理解"],
  project: ["项目描述", "解决方案", "风险与遗留问题", "结果验证"],
  moc: [],
  article: ["核心论点", "结语"],
  inbox: [],
};

// ---- Setup
const svg = d3.select("#viewport");
let width = window.innerWidth - 260;
let height = window.innerHeight;
svg.attr("viewBox", `0 0 ${width} ${height}`).attr("width", "100%").attr("height", "100%");
const g = svg.append("g");
const zoom = d3.zoom().scaleExtent([0.1, 5]).on("zoom", (e) => g.attr("transform", e.transform));
svg.call(zoom);
svg.on("click", (e) => { if (e.target.tagName === "svg") closeInfoPanel(); });

// ---- State
let currentView = "graph";
const activeTypes = new Set(["topic", "literature", "project", "concept", "moc", "article", "inbox"]);
let searchTerm = "";
let currentTopic = DATA.default_topic;

const nodesById = {};
DATA.nodes.forEach(n => { nodesById[n.id] = n; });

// d3.forceLink mutates edge.source / edge.target in place, replacing
// the original string IDs with node object references. That breaks any
// view that later tries to match edges by string ID. Helpers below
// always read the ID safely regardless of which state the edge is in.
function edgeSourceId(e) {
  return (e.source && typeof e.source === "object") ? e.source.id : e.source;
}
function edgeTargetId(e) {
  return (e.target && typeof e.target === "object") ? e.target.id : e.target;
}
// Cloned edge copy keeps DATA.edges immutable across view switches.
function cloneEdges(edges) {
  return edges.map(e => ({
    source: edgeSourceId(e),
    target: edgeTargetId(e),
    section: e.section,
    kind: e.kind,
  }));
}

// ---- Helpers
function escapeHTML(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, c => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c]
  ));
}

function shortLabel(s, maxLen) {
  if (!s) return "";
  let r = s.replace(/^(Literature - |Topic - |Concept - |Project - |MOC - )/, "");
  r = r.replace(/\s\d{4}-\d{2}-\d{2}$/, "");
  if (r.length > maxLen) r = r.slice(0, maxLen - 1) + "…";
  return r;
}

function clearG() { g.selectAll("*").remove(); }

function nodeSize(d) {
  if (currentView === "ego") return d.is_center ? 24 : (10 + Math.sqrt(d.in_degree || 0) * 3);
  return 6 + Math.sqrt(d.in_degree || 0) * 2.5;
}

// ---- Info panel
function openInfoPanel(d) {
  const app = document.getElementById("app");
  app.classList.add("with-panel");

  const cleanTitle = shortLabel(d.title || d.id || d.name, 80);
  const ntype = d.type || "unknown";
  const typeColor = RINGS[ntype] || "#6B7280";
  const typeLabel = TYPE_LABELS[ntype] || ntype;

  document.getElementById("ip-title").textContent = cleanTitle;

  const chips = [];
  chips.push(`<span class="ip-chip ip-chip-type" style="background:${typeColor}">${typeLabel}</span>`);
  if (d.in_degree !== undefined) {
    chips.push(`<span class="ip-chip ip-chip-meta">← ${d.in_degree} 入</span>`);
    chips.push(`<span class="ip-chip ip-chip-meta">→ ${d.out_degree} 出</span>`);
  }
  if (d.updated) chips.push(`<span class="ip-chip ip-chip-meta">📅 ${escapeHTML(d.updated)}</span>`);
  if (d.author) chips.push(`<span class="ip-chip ip-chip-meta">✍ ${escapeHTML(d.author)}</span>`);
  if (d.tags && d.tags.length) {
    d.tags.slice(0, 4).forEach(t => chips.push(`<span class="ip-chip ip-chip-tag">#${escapeHTML(t)}</span>`));
  }
  document.getElementById("ip-chips").innerHTML = chips.join("");

  const wikilink = `[[${d.title || d.id}]]`;
  const obsidianUri = d.rel_path
    ? `obsidian://open?path=${encodeURIComponent(DATA.vault_path + "/" + d.rel_path)}`
    : "";
  const actions = [];
  if (obsidianUri) {
    actions.push(`<button class="ip-btn ip-btn-primary" id="ip-btn-open">📂 在 Obsidian 打开</button>`);
  }
  actions.push(`<button class="ip-btn" id="ip-btn-copy">📋 复制 wikilink</button>`);
  if (d.source) {
    actions.push(`<button class="ip-btn" id="ip-btn-source">🔗 来源</button>`);
  }
  if (currentView !== "ego" && d.type === "topic") {
    actions.push(`<button class="ip-btn" id="ip-btn-ego">🎯 Ego 视图</button>`);
  }
  document.getElementById("ip-actions").innerHTML = actions.join("");
  if (obsidianUri) {
    document.getElementById("ip-btn-open").onclick = () => {
      window.location.href = obsidianUri;
      showToast("尝试在 Obsidian 中打开…");
    };
  }
  document.getElementById("ip-btn-copy").onclick = async () => {
    try {
      await navigator.clipboard.writeText(wikilink);
      showToast(`已复制：${wikilink}`);
    } catch (e) { showToast("复制失败"); }
  };
  if (d.source) {
    document.getElementById("ip-btn-source").onclick = () => window.open(d.source, "_blank");
  }
  const egoBtn = document.getElementById("ip-btn-ego");
  if (egoBtn) {
    egoBtn.onclick = () => { currentTopic = d.id; switchView("ego"); };
  }

  let body = "";
  if (d.summary) {
    body += `<div class="ip-summary">${escapeHTML(d.summary)}</div>`;
  } else {
    body += `<div class="ip-summary" style="color:#9CA3AF;font-style:italic;">无摘要</div>`;
  }

  if (d.source) {
    body += `<div class="ip-section">`;
    body += `<div class="ip-section-label">📎 来源</div>`;
    body += `<a class="ip-source-link" href="${escapeHTML(d.source)}" target="_blank">${escapeHTML(d.source)}</a>`;
    body += `</div>`;
  }

  const keyList = KEY_FIELDS[ntype] || [];
  const sectionContents = d.section_contents || {};
  const renderedKeys = new Set();
  if (keyList.length) {
    const keysFound = keyList.filter(k => sectionContents[k]);
    if (keysFound.length) {
      body += `<div class="ip-section">`;
      body += `<div class="ip-section-label">🎯 关键字段</div>`;
      keysFound.forEach(k => {
        body += `<div class="ip-key-field">`;
        body += `<div class="ip-key-field-name">${escapeHTML(k)}</div>`;
        body += `<div class="ip-key-field-content">${escapeHTML(sectionContents[k])}</div>`;
        body += `</div>`;
        renderedKeys.add(k);
      });
      body += `</div>`;
    }
  }

  if (d.forwardlinks_by_section && Object.keys(d.forwardlinks_by_section).length) {
    const fl = d.forwardlinks_by_section;
    const totalOut = Object.values(fl).reduce((a, b) => a + b.length, 0);
    body += `<div class="ip-section">`;
    body += `<div class="ip-section-label">→ 出链按区块分组 <span class="count">${totalOut}</span></div>`;
    Object.entries(fl).forEach(([sec, targets]) => {
      const secName = sec === "_frontmatter" ? "frontmatter.topic" : sec;
      body += `<div class="ip-fwd-row">`;
      body += `<span class="sec-name">${escapeHTML(secName)}</span>`;
      body += `<span class="count-badge">${targets.length}</span>`;
      body += `</div>`;
      targets.slice(0, 8).forEach(t => {
        const tn = nodesById[t];
        const tType = tn ? tn.type : "missing";
        const tColor = COLORS[tType] || "#FCA5A5";
        body += `<div class="ip-link-row" data-jump="${encodeURIComponent(t)}">`;
        body += `<span class="dot" style="width:7px;height:7px;border-radius:50%;background:${tColor};flex-shrink:0;"></span>`;
        body += `<span class="src">${escapeHTML(shortLabel(t, 36))}</span>`;
        if (!tn) body += `<span class="ip-chip ip-chip-broken" style="font-size:9px;padding:1px 6px;">断</span>`;
        body += `</div>`;
      });
      if (targets.length > 8) {
        body += `<div style="font-size:10px;color:#9CA3AF;padding:2px 8px;">+${targets.length - 8} 个…</div>`;
      }
    });
    body += `</div>`;
  }

  if (d.backlinks && d.backlinks.length) {
    body += `<div class="ip-section">`;
    body += `<div class="ip-section-label">← 被引用 <span class="count">${d.backlinks_total || d.backlinks.length}</span></div>`;
    d.backlinks.forEach(bl => {
      const fromNode = nodesById[bl.from];
      const fromType = fromNode ? fromNode.type : "missing";
      const fromColor = COLORS[fromType] || "#FCA5A5";
      const arrow = bl.kind === "implicit" ? "⋯" : "→";
      const secName = bl.section === "_frontmatter" ? "topic" : bl.section;
      body += `<div class="ip-link-row" data-jump="${encodeURIComponent(bl.from)}">`;
      body += `<span class="arrow">${arrow}</span>`;
      body += `<span class="dot" style="width:7px;height:7px;border-radius:50%;background:${fromColor};flex-shrink:0;"></span>`;
      body += `<span class="src">${escapeHTML(shortLabel(bl.from, 30))}</span>`;
      body += `<span class="sec">${escapeHTML(secName)}</span>`;
      body += `</div>`;
    });
    if (d.backlinks_total > d.backlinks.length) {
      body += `<div style="font-size:10px;color:#9CA3AF;padding:4px 8px;">+${d.backlinks_total - d.backlinks.length} 处…</div>`;
    }
    body += `</div>`;
  }

  const otherSections = Object.entries(sectionContents).filter(([k]) => !renderedKeys.has(k));
  if (otherSections.length) {
    body += `<details class="ip-section-detail">`;
    body += `<summary>📖 其他区块正文 (${otherSections.length})</summary>`;
    otherSections.forEach(([k, v]) => {
      body += `<div class="ip-key-field" style="background:#F9FAFB;border-color:#E5E7EB;">`;
      body += `<div class="ip-key-field-name" style="color:#4B5563;">${escapeHTML(k)}</div>`;
      body += `<div class="ip-key-field-content">${escapeHTML(v)}</div>`;
      body += `</div>`;
    });
    body += `</details>`;
  }

  if (d.rel_path) {
    body += `<div class="ip-section" style="margin-top:24px;border-top:1px solid #F3F4F6;padding-top:12px;">`;
    body += `<div class="ip-section-label">📁 路径</div>`;
    body += `<div style="font-size:11px;color:#6B7280;word-break:break-all;font-family:monospace;">${escapeHTML(d.rel_path)}</div>`;
    body += `</div>`;
  }

  const bodyEl = document.getElementById("ip-body");
  bodyEl.innerHTML = body;
  bodyEl.querySelectorAll("[data-jump]").forEach(el => {
    el.addEventListener("click", (e) => {
      const id = decodeURIComponent(el.dataset.jump);
      const target = nodesById[id];
      if (target) openInfoPanel(target);
      else showToast("目标笔记不存在（断链）");
    });
  });
}

function closeInfoPanel() {
  document.getElementById("app").classList.remove("with-panel");
}

function showToast(msg) {
  const t = document.getElementById("ip-toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 1800);
}

document.querySelector(".ip-close").addEventListener("click", closeInfoPanel);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeInfoPanel();
});

// ---- Graph view
function renderGraph() {
  clearG();
  const filteredNodes = DATA.nodes.filter(n =>
    activeTypes.has(n.type) &&
    (searchTerm === "" || n.title.toLowerCase().includes(searchTerm))
  ).map(n => ({...n}));  // clone so drag.fx/fy doesn't pollute DATA.nodes
  const nodeIds = new Set(filteredNodes.map(n => n.id));
  // Clone edges so d3.forceLink can mutate freely without affecting DATA.edges.
  const filteredEdges = cloneEdges(
    DATA.edges.filter(e => nodeIds.has(edgeSourceId(e)) && nodeIds.has(edgeTargetId(e)))
  );

  const sim = d3.forceSimulation(filteredNodes)
    .force("link", d3.forceLink(filteredEdges).id(d => d.id).distance(60).strength(0.6))
    .force("charge", d3.forceManyBody().strength(-180))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collide", d3.forceCollide().radius(d => nodeSize(d) + 4));

  const link = g.append("g").selectAll("line")
    .data(filteredEdges).join("line")
    .attr("class", d => "link-" + d.kind);

  const node = g.append("g").selectAll("g")
    .data(filteredNodes).join("g")
    .call(d3.drag()
      .on("start", (event, d) => {
        if (!event.active) sim.alphaTarget(0.3).restart();
        d.fx = d.x; d.fy = d.y;
      })
      .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
      .on("end", (event, d) => {
        if (!event.active) sim.alphaTarget(0);
        d.fx = null; d.fy = null;
      }));

  node.append("circle")
    .attr("class", "node-circle")
    .attr("r", nodeSize)
    .attr("fill", d => COLORS[d.type] || "#999")
    .attr("stroke", d => RINGS[d.type] || "#666")
    .attr("stroke-width", 1.8)
    .on("mouseover", function (event, d) {
      const connected = new Set([d.id]);
      filteredEdges.forEach(e => {
        const s = edgeSourceId(e), t = edgeTargetId(e);
        if (s === d.id) connected.add(t);
        if (t === d.id) connected.add(s);
      });
      node.classed("node-dim", n => !connected.has(n.id));
      link.classed("link-highlight",
            e => edgeSourceId(e) === d.id || edgeTargetId(e) === d.id)
          .classed("node-dim",
            e => edgeSourceId(e) !== d.id && edgeTargetId(e) !== d.id);
    })
    .on("mouseout", function () {
      node.classed("node-dim", false);
      link.classed("link-highlight", false).classed("node-dim", false);
    })
    .on("click", (event, d) => { event.stopPropagation(); openInfoPanel(d); });

  node.append("text")
    .attr("class", "node-label")
    .attr("dy", d => nodeSize(d) + 11)
    .attr("text-anchor", "middle")
    .text(d => shortLabel(d.title, 16))
    .style("font-size", d => (d.in_degree > 5 ? "12px" : "10px"))
    .style("font-weight", d => (d.in_degree > 5 ? "600" : "400"));

  sim.on("tick", () => {
    link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    node.attr("transform", d => `translate(${d.x},${d.y})`);
  });
}

// ---- Ego view
function renderEgo(centerId) {
  clearG();
  centerId = centerId || DATA.default_topic;
  if (!centerId) return;
  const neighbors = new Set();
  DATA.edges.forEach(e => {
    const s = edgeSourceId(e), t = edgeTargetId(e);
    if (t === centerId) neighbors.add(s);
    if (s === centerId) neighbors.add(t);
  });
  const keep = new Set([centerId, ...neighbors]);
  const nodesData = DATA.nodes.filter(n => keep.has(n.id) && activeTypes.has(n.type)).map(n => ({...n}));
  nodesData.forEach(n => { n.is_center = (n.id === centerId); });
  const nodeIds = new Set(nodesData.map(n => n.id));
  const edgesData = cloneEdges(
    DATA.edges.filter(e => nodeIds.has(edgeSourceId(e)) && nodeIds.has(edgeTargetId(e)))
  );

  const cx = width / 2, cy = height / 2;
  const R = Math.min(width, height) * 0.35;
  const others = nodesData.filter(n => !n.is_center);
  others.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / others.length - Math.PI / 2;
    n.fx = cx + R * Math.cos(angle);
    n.fy = cy + R * Math.sin(angle);
  });
  const center = nodesData.find(n => n.is_center);
  if (center) { center.fx = cx; center.fy = cy; }

  const sim = d3.forceSimulation(nodesData)
    .force("link", d3.forceLink(edgesData).id(d => d.id).distance(80))
    .force("charge", d3.forceManyBody().strength(-200))
    .force("collide", d3.forceCollide().radius(d => nodeSize(d) + 6));

  const link = g.append("g").selectAll("line")
    .data(edgesData).join("line")
    .attr("class", d => "link-" + d.kind);

  const node = g.append("g").selectAll("g")
    .data(nodesData).join("g");

  node.append("circle")
    .attr("class", "node-circle")
    .attr("r", nodeSize)
    .attr("fill", d => COLORS[d.type] || "#999")
    .attr("stroke", d => RINGS[d.type] || "#666")
    .attr("stroke-width", d => d.is_center ? 3 : 2)
    .on("click", (event, d) => { event.stopPropagation(); openInfoPanel(d); });

  node.append("text")
    .attr("class", "node-label")
    .attr("dy", d => d.is_center ? 4 : nodeSize(d) + 13)
    .attr("text-anchor", "middle")
    .text(d => shortLabel(d.title, d.is_center ? 28 : 16))
    .style("font-size", d => d.is_center ? "13px" : "11px")
    .style("font-weight", d => d.is_center ? "700" : "500")
    .style("fill", d => d.is_center ? "white" : "#1F2937");

  sim.on("tick", () => {
    link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    node.attr("transform", d => `translate(${d.x},${d.y})`);
  });
}

// ---- Mindmap view
function renderMindmap(rootData) {
  clearG();
  if (!rootData || !rootData.children || rootData.children.length === 0) {
    g.append("text").attr("x", width / 2).attr("y", height / 2)
      .attr("text-anchor", "middle").attr("font-size", 16).attr("fill", "#9CA3AF")
      .text("(no content)");
    return;
  }

  const root = d3.hierarchy(rootData);
  const tree = d3.tree()
    .size([2 * Math.PI, Math.min(width, height) / 2 - 100])
    .separation((a, b) => (a.parent === b.parent ? 1 : 2) / Math.max(a.depth, 1));
  tree(root);

  const cx = width / 2, cy = height / 2;
  const radialPoint = (a, r) => [cx + r * Math.cos(a - Math.PI / 2), cy + r * Math.sin(a - Math.PI / 2)];

  g.append("g").selectAll("path")
    .data(root.links()).join("path")
    .attr("class", "mindmap-link")
    .attr("d", d3.linkRadial()
      .angle(d => d.x)
      .radius(d => d.y)
      .source(d => ({x: d.source.x, y: d.source.y}))
      .target(d => ({x: d.target.x, y: d.target.y})))
    .attr("transform", `translate(${cx},${cy})`);

  const node = g.append("g").selectAll("g")
    .data(root.descendants()).join("g")
    .attr("transform", d => {
      const [x, y] = radialPoint(d.x, d.y);
      return `translate(${x},${y})`;
    });

  node.each(function (d) {
    const sel = d3.select(this);
    const label = shortLabel(d.data.name, d.depth === 0 ? 30 : 22);
    const isRoot = d.depth === 0;
    const isHealthBucket = String(d.data.type || "").startsWith("health_");
    const isSection = d.data.type === "section" || d.data.type === "type_group" || isHealthBucket;
    const fontSize = isRoot ? 13 : (isSection ? 12 : 11);
    const padding = isRoot ? 12 : 8;
    const fill = COLORS[d.data.type] || "#E5E7EB";
    const whiteTextTypes = ["project", "topic_root", "vault_root",
                            "health_orphan", "health_broken", "health_draft",
                            "health_stale", "health_shell"];
    const textColor = (isRoot || whiteTextTypes.includes(d.data.type)) ? "white" : "#1F2937";

    const text = sel.append("text")
      .text(label)
      .attr("font-size", fontSize)
      .attr("font-weight", isRoot ? 700 : (isSection ? 600 : 400))
      .attr("fill", textColor)
      .attr("text-anchor", "middle")
      .attr("dy", "0.32em");
    const bbox = text.node().getBBox();
    sel.insert("rect", "text")
      .attr("x", bbox.x - padding)
      .attr("y", bbox.y - padding / 2)
      .attr("width", bbox.width + padding * 2)
      .attr("height", bbox.height + padding)
      .attr("rx", 6)
      .attr("fill", fill)
      .attr("stroke", RINGS[d.data.type] || "#D1D5DB")
      .attr("stroke-width", 1.5)
      .style("cursor", d.data.name && nodesById[d.data.name] ? "pointer" : "default")
      .on("click", (event) => {
        event.stopPropagation();
        const tgt = nodesById[d.data.name];
        if (tgt) openInfoPanel(tgt);
      });

    if (d.data.missing) {
      sel.select("rect").attr("stroke", "#EF4444").attr("stroke-dasharray", "4,3");
    }
  });
}

// ---- Health view (HTML accordion, scales to thousands of items)
const HEALTH_BUCKET_META = {
  health_orphan: {icon: "🔴", title: "孤儿",
                  hint: "完全没人引用、自己也没引用别人"},
  health_broken: {icon: "🟠", title: "含断链",
                  hint: "笔记里 [[wikilink]] 指向不存在的目标"},
  health_draft:  {icon: "🟣", title: "草稿",
                  hint: "status: draft，未参与图谱拓扑"},
  health_stale:  {icon: "🟡", title: "陈旧",
                  hint: "updated 超过 90 天或缺失"},
  health_shell:  {icon: "⚫", title: "空壳",
                  hint: "所有区块都是 _待补充_"},
};
const HEALTH_BUCKET_ORDER = [
  "health_orphan", "health_broken", "health_draft",
  "health_stale", "health_shell",
];

function renderHealth() {
  const wrap = document.getElementById("health-viewport");
  const tree = DATA.health_tree || {children: []};
  const bucketsByType = {};
  tree.children.forEach(c => { bucketsByType[c.type] = c; });

  let html = `<div class="health-wrap">`;
  html += `<h1 class="health-h1">🏥 Vault 健康报告</h1>`;
  html += `<div class="health-sub">扫了 ${DATA.stats.nodes} 个非草稿节点 + ${DATA.drafts_count || 0} 篇草稿。下面列出 5 类需要关注的笔记。</div>`;

  // Summary tiles
  html += `<div class="health-summary">`;
  HEALTH_BUCKET_ORDER.forEach(t => {
    const meta = HEALTH_BUCKET_META[t];
    const b = bucketsByType[t];
    const count = b ? b.children.length : 0;
    const cls = count === 0 ? "empty" : "";
    const color = COLORS[t] || "#9CA3AF";
    html += `<div class="health-stat ${cls}">`;
    html += `<div class="count" style="color:${count > 0 ? color : ""}">${count}</div>`;
    html += `<div class="label">${meta.icon} ${meta.title}</div>`;
    html += `</div>`;
  });
  html += `</div>`;

  // Toolbar
  html += `<div class="health-toolbar">`;
  html += `<button id="health-expand-all">全部展开</button>`;
  html += `<button id="health-collapse-all">全部折叠</button>`;
  html += `</div>`;

  // Buckets
  let totalIssues = 0;
  HEALTH_BUCKET_ORDER.forEach(t => {
    const meta = HEALTH_BUCKET_META[t];
    const b = bucketsByType[t];
    const items = b ? b.children : [];
    totalIssues += items.length;
    // Show even empty buckets so the structure is consistent; collapse them.
    const collapsedCls = items.length === 0 ? "collapsed" : "";
    html += `<div class="health-bucket ${collapsedCls}" data-bucket="${t}">`;
    html += `<div class="health-bucket-header">`;
    html += `<span class="health-bucket-icon">${meta.icon}</span>`;
    html += `<span class="health-bucket-title">${meta.title}`;
    html += `<span style="font-weight:400;color:#6B7280;font-size:12px;margin-left:6px;">— ${meta.hint}</span>`;
    html += `</span>`;
    html += `<span class="health-bucket-count">${items.length}</span>`;
    html += `<span class="chev">▼</span>`;
    html += `</div>`;
    html += `<div class="health-bucket-body">`;
    if (items.length === 0) {
      html += `<div class="health-empty">无</div>`;
    } else {
      items.forEach(item => {
        const dotColor = COLORS[item.type] || "#9CA3AF";
        const summary = item.summary || "";
        html += `<div class="health-item" data-jump="${encodeURIComponent(item.name)}">`;
        html += `<span class="type-dot" style="background:${dotColor}"></span>`;
        html += `<span class="title">${escapeHTML(shortLabel(item.name, 60))}</span>`;
        if (summary) {
          html += `<span class="meta">${escapeHTML(summary.length > 70 ? summary.slice(0, 70) + "…" : summary)}</span>`;
        }
        html += `</div>`;
      });
    }
    html += `</div></div>`;
  });

  if (totalIssues === 0) {
    html += `<div style="text-align:center;padding:40px;color:#34D399;font-size:14px;">`;
    html += `✓ Vault 一切健康，没有需要关注的笔记`;
    html += `</div>`;
  }

  html += `</div>`;
  wrap.innerHTML = html;

  // Wire up bucket collapsing
  wrap.querySelectorAll(".health-bucket-header").forEach(h => {
    h.addEventListener("click", () => {
      h.parentElement.classList.toggle("collapsed");
    });
  });
  // Wire up item clicks → info panel
  wrap.querySelectorAll(".health-item[data-jump]").forEach(el => {
    el.addEventListener("click", () => {
      const id = decodeURIComponent(el.dataset.jump);
      const target = nodesById[id];
      if (target) openInfoPanel(target);
      else showToast("目标笔记不在图谱中（可能是草稿或断链目标）");
    });
  });
  // Expand / collapse all
  const expandBtn = document.getElementById("health-expand-all");
  if (expandBtn) {
    expandBtn.addEventListener("click", () => {
      wrap.querySelectorAll(".health-bucket").forEach(b => b.classList.remove("collapsed"));
    });
  }
  const collapseBtn = document.getElementById("health-collapse-all");
  if (collapseBtn) {
    collapseBtn.addEventListener("click", () => {
      wrap.querySelectorAll(".health-bucket").forEach(b => b.classList.add("collapsed"));
    });
  }
}

// ---- View routing
function switchView(view) {
  currentView = view;
  document.querySelectorAll(".view-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.view === view);
  });
  document.getElementById("topic-picker-section").style.display =
    (view === "ego" || view === "mindmap-topic") ? "block" : "none";
  document.getElementById("filter-section").style.display =
    (view === "graph" || view === "ego") ? "block" : "none";

  // Health view uses an HTML accordion overlay, not the SVG canvas.
  document.body.classList.toggle("health-active", view === "health");

  const titles = {
    "graph": "Graph · 全量力导向图",
    "ego": `Ego · ${shortLabel(currentTopic || "", 40)}`,
    "mindmap-topic": `Mindmap · ${shortLabel(currentTopic || "", 40)}`,
    "health": "Health · 健康检查",
  };
  document.getElementById("view-title").textContent = titles[view];

  if (view === "graph") renderGraph();
  else if (view === "ego") renderEgo(currentTopic);
  else if (view === "mindmap-topic") renderMindmap(DATA.all_topic_mindmaps[currentTopic]);
  else if (view === "health") renderHealth();
}

// ---- Init
document.querySelectorAll(".view-btn").forEach(btn => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});
document.querySelectorAll("[data-type]").forEach(cb => {
  cb.addEventListener("change", () => {
    if (cb.checked) activeTypes.add(cb.dataset.type);
    else activeTypes.delete(cb.dataset.type);
    if (currentView === "graph") renderGraph();
    if (currentView === "ego") renderEgo(currentTopic);
  });
});
document.getElementById("search-input").addEventListener("input", (e) => {
  searchTerm = e.target.value.toLowerCase();
  if (currentView === "graph") renderGraph();
});
const picker = document.getElementById("topic-picker");
DATA.topics.forEach(t => {
  const opt = document.createElement("option");
  opt.value = t; opt.textContent = shortLabel(t, 40);
  if (t === currentTopic) opt.selected = true;
  picker.appendChild(opt);
});
picker.addEventListener("change", (e) => {
  currentTopic = e.target.value;
  switchView(currentView);
});
document.getElementById("btn-reset").addEventListener("click", () => {
  svg.transition().duration(400).call(zoom.transform, d3.zoomIdentity);
});
document.getElementById("btn-zoomin").addEventListener("click", () => {
  svg.transition().duration(200).call(zoom.scaleBy, 1.3);
});
document.getElementById("btn-zoomout").addEventListener("click", () => {
  svg.transition().duration(200).call(zoom.scaleBy, 1 / 1.3);
});

// Type counts
const typeCounts = {};
DATA.nodes.forEach(n => { typeCounts[n.type] = (typeCounts[n.type] || 0) + 1; });
Object.keys(typeCounts).forEach(t => {
  const el = document.querySelector(`[data-count="${t}"]`);
  if (el) el.textContent = typeCounts[t];
});

// Stats
const s = DATA.stats;
document.getElementById("stats").innerHTML =
  `节点 <strong>${s.nodes}</strong>（已排除草稿）<br>` +
  `边 <strong>${s.edges}</strong>（显式 ${s.explicit} / 隐式 ${s.implicit}）<br>` +
  `断链 <strong>${s.broken}</strong>`;

// Optional initial filter from CLI flag
if (DATA.filter_type) {
  activeTypes.clear();
  activeTypes.add(DATA.filter_type);
  document.querySelectorAll("[data-type]").forEach(cb => {
    cb.checked = (cb.dataset.type === DATA.filter_type);
  });
}

window.addEventListener("resize", () => {
  width = window.innerWidth - (document.getElementById("app").classList.contains("with-panel") ? 680 : 260);
  height = window.innerHeight;
  svg.attr("viewBox", `0 0 ${width} ${height}`);
  switchView(currentView);
});

switchView("graph");
</script>
</body>
</html>
"""
