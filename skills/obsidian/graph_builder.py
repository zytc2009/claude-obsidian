"""
graph_builder.py — Scan a vault and build a node/edge graph model.

Pure data layer for the ``--type graph`` viewer. Reads markdown files
under the managed ``INDEX_DIRS``, extracts wikilink edges and
``frontmatter.topic`` implicit edges, and computes backlinks and
forward-link distribution by H2 section.

Drafts (``status: draft``) are excluded by default. Pass
``include_inbox=True`` to ``build_graph`` to also scan ``00-Inbox``.

No external dependencies beyond stdlib.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    from . import frontmatter as fm
    from .index import INDEX_DIRS
except ImportError:  # script-mode fallback
    import frontmatter as fm  # type: ignore[no-redef]
    from index import INDEX_DIRS  # type: ignore[no-redef]


# Inline list parsing (``tags: [a, b, c]``) — frontmatter.parse keeps the
# raw string, so we split it here.
_INLINE_LIST_RE = re.compile(r"^\[(.*)\]$")

# Maximum characters retained per H2 section in the embedded JSON. Keeps
# the generated HTML manageable; the in-vault note is the source of
# truth, the viewer is a summary.
SECTION_CONTENT_CAP = 600

# H2 section splitting. Capture the heading text on its own line.
_H2_SPLIT_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class GraphNode:
    id: str
    type: str
    title: str
    summary: str
    status: str
    updated: str
    created: str
    tags: list[str]
    author: str
    source: str
    rel_path: str
    in_degree: int
    out_degree: int
    section_contents: dict[str, str]
    backlinks: list[dict[str, str]]
    forwardlinks_by_section: dict[str, list[str]]
    backlinks_total: int


@dataclass
class GraphEdge:
    source: str
    target: str
    section: str
    kind: str  # "explicit" | "implicit"


@dataclass
class VaultGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    broken: list[str]  # target stems referenced but not found
    topics: list[str]  # all topic stems, sorted

    def stats(self) -> dict[str, int]:
        explicit = sum(1 for e in self.edges if e.kind == "explicit")
        implicit = sum(1 for e in self.edges if e.kind == "implicit")
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "explicit": explicit,
            "implicit": implicit,
            "broken": len(self.broken),
        }


def _parse_inline_list(raw: str) -> list[str]:
    """Parse ``[a, "b", 'c']`` into ``[a, b, c]``. Returns ``[]`` if not a list."""

    raw = raw.strip()
    m = _INLINE_LIST_RE.match(raw)
    if not m:
        return []
    inner = m.group(1).strip()
    if not inner:
        return []
    out: list[str] = []
    for raw_item in inner.split(","):
        item = raw_item.strip().strip('"').strip("'")
        if item:
            out.append(item)
    return out


def _parse_sections(body: str) -> dict[str, str]:
    """Split body by ``## H2`` and return ``{name: content}``.

    Preserves order via dict insertion order (Python 3.7+).
    """

    parts = _H2_SPLIT_RE.split(body)
    # parts: [pre_text, h2_1, content_1, h2_2, content_2, ...]
    result: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        name = parts[i].strip()
        content = parts[i + 1] if i + 1 < len(parts) else ""
        result[name] = content.strip()
    return result


def _pick_summary(fmd: dict[str, str], sections: dict[str, str]) -> str:
    """Pick a single-line summary for the tooltip / panel header."""

    for key in ("主题说明", "一句话定义", "解决的问题", "项目描述"):
        val = fmd.get(key, "").strip().strip('"').strip("'")
        if val and val != "_待补充_":
            return val[:140]
    for content in sections.values():
        c = content.strip()
        if c and c != "_待补充_" and not c.startswith("[["):
            line = c.split("\n")[0].strip()
            if line:
                return line[:140]
    return ""


def _truncate_sections(sections: dict[str, str]) -> dict[str, str]:
    """Cap each section content to SECTION_CONTENT_CAP chars, drop empty ones."""

    out: dict[str, str] = {}
    for name, content in sections.items():
        c = content.strip()
        if not c or c == "_待补充_":
            continue
        if len(c) > SECTION_CONTENT_CAP:
            c = c[:SECTION_CONTENT_CAP] + "…"
        out[name] = c
    return out


def _normalize_topic_target(raw: str) -> str:
    """``"X"`` → ``"Topic - X"`` unless already prefixed."""

    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return ""
    if raw.startswith("Topic - "):
        return raw
    return f"Topic - {raw}"


def _scan_dirs(include_inbox: bool) -> list[tuple[str, str]]:
    """Return list of (rel_dir, ntype) pairs to scan."""

    dirs = list(INDEX_DIRS)
    if include_inbox:
        dirs.append(("00-Inbox", "inbox"))
    return dirs


def _node_type_from_dir(rel_dir: str) -> str:
    """Map a managed dir prefix to a node type."""

    if rel_dir.endswith("Topics"):
        return "topic"
    if rel_dir.endswith("MOCs"):
        return "moc"
    if rel_dir.endswith("Concepts"):
        return "concept"
    if rel_dir.endswith("Literature"):
        return "literature"
    if rel_dir.startswith("02-Projects"):
        return "project"
    if rel_dir.startswith("06-Articles"):
        return "article"
    if rel_dir.startswith("00-Inbox"):
        return "inbox"
    return "unknown"


def build_graph(vault: Path, *, include_inbox: bool = False,
                exclude_draft: bool = True) -> VaultGraph:
    """Scan ``vault`` and build the graph model.

    :param vault: vault root containing managed dirs.
    :param include_inbox: include ``00-Inbox`` notes (default False).
    :param exclude_draft: skip notes with ``status: draft`` (default True).
    """

    # First pass: collect notes
    raw_nodes: dict[str, dict[str, Any]] = {}
    explicit_edges: list[GraphEdge] = []
    implicit_edges: list[GraphEdge] = []

    for rel_dir, _legacy_ntype in _scan_dirs(include_inbox):
        d = vault / rel_dir
        if not d.exists():
            continue
        ntype = _node_type_from_dir(rel_dir)
        for path in d.glob("*.md"):
            stem = path.stem
            text = path.read_text(encoding="utf-8", errors="replace")
            fmd, body = fm.parse(text)
            status = fmd.get("status", "active").strip()
            if exclude_draft and status == "draft":
                continue
            sections = _parse_sections(body)
            summary = _pick_summary(fmd, sections)
            tags = _parse_inline_list(fmd.get("tags", ""))
            topics_fm = _parse_inline_list(fmd.get("topic", ""))
            rel_path = str(path.relative_to(vault)).replace("\\", "/")

            raw_nodes[stem] = {
                "type": ntype,
                "title": stem,
                "summary": summary,
                "status": status,
                "updated": fmd.get("updated", "").strip(),
                "created": fmd.get("created", "").strip(),
                "tags": tags,
                "author": fmd.get("author", "").strip().strip('"').strip("'"),
                "source": fmd.get("source", "").strip().strip('"').strip("'"),
                "rel_path": rel_path,
                "section_contents": _truncate_sections(sections),
            }

            # Explicit wikilink edges per section
            for sec_name, sec_content in sections.items():
                seen_in_section: set[str] = set()
                for match in fm._WIKILINK_RE.finditer(sec_content):
                    target = match.group(1).strip().rsplit("/", 1)[-1]
                    if not target or target == stem:
                        continue
                    if target in seen_in_section:
                        continue
                    seen_in_section.add(target)
                    explicit_edges.append(GraphEdge(
                        source=stem, target=target,
                        section=sec_name, kind="explicit",
                    ))

            # Implicit edges via frontmatter.topic
            for raw in topics_fm:
                tgt = _normalize_topic_target(raw)
                if not tgt:
                    continue
                implicit_edges.append(GraphEdge(
                    source=stem, target=tgt,
                    section="_frontmatter", kind="implicit",
                ))

    all_edges = explicit_edges + implicit_edges

    # Degrees
    in_deg: Counter[str] = Counter()
    out_deg: Counter[str] = Counter()
    for e in all_edges:
        if e.target in raw_nodes:
            in_deg[e.target] += 1
        if e.source in raw_nodes:
            out_deg[e.source] += 1

    # Backlinks per node
    backlinks_map: dict[str, list[dict[str, str]]] = defaultdict(list)
    forwardlinks_map: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for e in explicit_edges:
        backlinks_map[e.target].append({
            "from": e.source, "section": e.section, "kind": "explicit",
        })
        # de-dupe inside same section
        bucket = forwardlinks_map[e.source][e.section]
        if e.target not in bucket:
            bucket.append(e.target)
    for e in implicit_edges:
        backlinks_map[e.target].append({
            "from": e.source, "section": "_frontmatter", "kind": "implicit",
        })

    # Assemble GraphNode list
    nodes: list[GraphNode] = []
    for stem, meta in raw_nodes.items():
        bl_total = len(backlinks_map.get(stem, []))
        # cap backlinks for tooltip; keep total separately
        bl_capped = backlinks_map.get(stem, [])[:8]
        fl = {
            sec: targets
            for sec, targets in forwardlinks_map.get(stem, {}).items()
        }
        nodes.append(GraphNode(
            id=stem,
            type=meta["type"],
            title=meta["title"],
            summary=meta["summary"],
            status=meta["status"],
            updated=meta["updated"],
            created=meta["created"],
            tags=meta["tags"],
            author=meta["author"],
            source=meta["source"],
            rel_path=meta["rel_path"],
            in_degree=in_deg.get(stem, 0),
            out_degree=out_deg.get(stem, 0),
            section_contents=meta["section_contents"],
            backlinks=bl_capped,
            forwardlinks_by_section=fl,
            backlinks_total=bl_total,
        ))

    # Broken link targets: referenced but not found among nodes
    referenced = {e.target for e in all_edges}
    broken = sorted(referenced - set(raw_nodes.keys()))

    topics = sorted(stem for stem, m in raw_nodes.items() if m["type"] == "topic")

    return VaultGraph(
        nodes=nodes,
        edges=all_edges,
        broken=broken,
        topics=topics,
    )


# ---------------------------------------------------------------------------
# Mindmap helpers (tree-shaped data derived from sections)
# ---------------------------------------------------------------------------


def build_topic_mindmap(vault: Path, topic_stem: str,
                        graph: VaultGraph) -> dict[str, Any]:
    """Build a hierarchical mindmap rooted at the given topic note.

    Structure::

        topic_root
          └─ section name (H2)
              └─ wikilink target  (leaf with type + summary + missing flag)
    """

    node_lookup = {n.id: n for n in graph.nodes}
    if topic_stem not in node_lookup:
        return {"name": topic_stem, "type": "missing", "children": []}

    # Find the file again to read raw sections (full content, not truncated)
    candidates = list(vault.glob(f"**/{topic_stem}.md"))
    if not candidates:
        return {"name": topic_stem, "type": node_lookup[topic_stem].type, "children": []}
    text = candidates[0].read_text(encoding="utf-8", errors="replace")
    _, body = fm.parse(text)
    sections = _parse_sections(body)

    root = {
        "name": topic_stem,
        "type": "topic_root",
        "summary": node_lookup[topic_stem].summary,
        "children": [],
    }
    for sec_name, content in sections.items():
        if not content.strip() or content.strip() == "_待补充_":
            continue
        sec_node: dict[str, Any] = {
            "name": sec_name, "type": "section", "children": []
        }
        seen: set[str] = set()
        for m in fm._WIKILINK_RE.finditer(content):
            target = m.group(1).strip().rsplit("/", 1)[-1]
            if target in seen:
                continue
            seen.add(target)
            tgt_node = node_lookup.get(target)
            sec_node["children"].append({
                "name": target,
                "type": tgt_node.type if tgt_node else "missing",
                "summary": tgt_node.summary if tgt_node else "",
                "missing": tgt_node is None,
            })
        # If section has prose but no wikilinks, surface the first line
        if not sec_node["children"]:
            prose = re.sub(r"\s+", " ", content).strip()
            if len(prose) > 5:
                sec_node["children"].append({
                    "name": prose[:80] + ("…" if len(prose) > 80 else ""),
                    "type": "prose",
                    "summary": "",
                    "missing": False,
                })
        if sec_node["children"]:
            root["children"].append(sec_node)
    return root


@dataclass
class DraftNote:
    """Minimal info about a draft (excluded from the graph itself)."""

    id: str
    type: str
    summary: str
    updated: str
    rel_path: str


def scan_drafts(vault: Path) -> list[DraftNote]:
    """Find ``status: draft`` notes in managed dirs.

    The main graph excludes drafts so they don't pollute topology, but
    the Health view surfaces them as a progress signal. Inbox is
    intentionally not scanned here: ``00-Inbox`` is its own pipeline
    stage and ``lint`` already reports inbox backlog.
    """

    drafts: list[DraftNote] = []
    for rel_dir, _legacy in INDEX_DIRS:
        d = vault / rel_dir
        if not d.exists():
            continue
        ntype = _node_type_from_dir(rel_dir)
        for path in d.glob("*.md"):
            text = path.read_text(encoding="utf-8", errors="replace")
            fmd, body = fm.parse(text)
            if fmd.get("status", "active").strip() != "draft":
                continue
            sections = _parse_sections(body)
            drafts.append(DraftNote(
                id=path.stem,
                type=ntype,
                summary=_pick_summary(fmd, sections),
                updated=fmd.get("updated", "").strip(),
                rel_path=str(path.relative_to(vault)).replace("\\", "/"),
            ))
    return drafts


# Threshold for ``陈旧`` (stale) classification in build_health_tree.
STALE_THRESHOLD_DAYS = 90


def _is_stale(updated_str: str, today: date | None = None) -> bool:
    """A note is stale if its ``updated`` is older than the threshold,
    or missing entirely (we cannot date-confirm freshness)."""

    today = today or date.today()
    if not updated_str:
        return True
    try:
        u = date.fromisoformat(updated_str)
    except ValueError:
        return True
    return (today - u).days > STALE_THRESHOLD_DAYS


def build_health_tree(graph: VaultGraph, drafts: list[DraftNote],
                      *, today: date | None = None) -> dict[str, Any]:
    """Build a 5-bucket health tree for the vault-wide overview view.

    Buckets:
      * 🔴 孤儿 — in_degree == 0 AND out_degree == 0
      * 🟠 含断链 — node references at least one broken target
      * 🟣 草稿 — status == draft (from ``drafts`` arg, not in graph)
      * 🟡 陈旧 — status == active AND updated > STALE_THRESHOLD_DAYS days ago
      * ⚫ 空壳 — section_contents is empty (every section was ``_待补充_``)

    Empty buckets are omitted from the tree.
    """

    today = today or date.today()
    broken_set = set(graph.broken)

    orphans: list[GraphNode] = []
    has_broken: list[tuple[GraphNode, list[str]]] = []
    stale: list[GraphNode] = []
    shells: list[GraphNode] = []

    for n in graph.nodes:
        if n.in_degree == 0 and n.out_degree == 0:
            orphans.append(n)
        broken_targets = []
        for section_targets in n.forwardlinks_by_section.values():
            for tgt in section_targets:
                if tgt in broken_set:
                    broken_targets.append(tgt)
        if broken_targets:
            has_broken.append((n, broken_targets))
        if _is_stale(n.updated, today):
            stale.append(n)
        if not n.section_contents:
            shells.append(n)

    def _leaf(n: GraphNode, extra: str = "") -> dict[str, Any]:
        return {
            "name": n.id,
            "type": n.type,
            "summary": (extra + " · " if extra else "") + (n.summary or ""),
            "missing": False,
        }

    root: dict[str, Any] = {
        "name": "Vault Health", "type": "vault_root", "children": []
    }

    def _bucket(label: str, items: list[dict[str, Any]],
                bucket_type: str) -> dict[str, Any] | None:
        if not items:
            return None
        return {
            "name": f"{label} ({len(items)})",
            "type": bucket_type,
            "children": items,
        }

    bucket_specs = [
        ("🔴 孤儿", "health_orphan",
         [_leaf(n) for n in sorted(orphans, key=lambda x: x.id)]),
        ("🟠 含断链", "health_broken",
         [_leaf(n, "→ " + ", ".join(set(targets))[:60])
          for n, targets in sorted(has_broken, key=lambda x: -len(x[1]))]),
        ("🟣 草稿", "health_draft",
         [{"name": d.id, "type": d.type,
           "summary": d.summary or "(draft)", "missing": False}
          for d in sorted(drafts, key=lambda x: x.id)]),
        ("🟡 陈旧 (>" + str(STALE_THRESHOLD_DAYS) + "天)", "health_stale",
         [_leaf(n, n.updated or "no date")
          for n in sorted(stale, key=lambda x: x.updated)]),
        ("⚫ 空壳", "health_shell",
         [_leaf(n) for n in sorted(shells, key=lambda x: x.id)]),
    ]
    for label, bucket_type, items in bucket_specs:
        bucket = _bucket(label, items, bucket_type)
        if bucket:
            root["children"].append(bucket)
    return root
