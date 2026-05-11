# Graph viewer — implementation plan

**Date:** 2026-05-11
**Status:** completed
**Spec:** `docs/specs/2026-05-11-graph-viewer-design.md`

## Context

User wants to "查看 vault 的知识图谱 + 思维导图"。
Constraints (already-stated red lines, not negotiable):

- Pure Python, zero new dependencies (no `networkx`, no `pyvis`).
- D3 from CDN with SRI hash (mirroring the `code-review-graph` HTML-rendering convention; product form is otherwise unrelated).
- Drafts excluded by default; `00-Inbox` excluded by default.
- `frontmatter.topic` field participates as an implicit (dashed) edge.
- Filename → type inference (don't trust `frontmatter.type`).

A standalone demo at `F:/whb/study/build_kg_demo.py` validated the visual approach against the real vault before porting.

## Steps

| # | Step | File(s) | Tests |
|---|------|---------|-------|
| 1 | `graph_builder.py` — pure data layer | `skills/obsidian/graph_builder.py` | `tests/test_graph_builder.py` (14) |
| 2 | `graph_view.py` — HTML template renderer | `skills/obsidian/graph_view.py` | `tests/test_graph_view.py` (9) |
| 3 | CLI dispatch | `skills/obsidian/cli.py` | covered indirectly via end-to-end run |
| 4 | SKILL trigger words + `MODE: graph` doc | `skills/obsidian/SKILL.md` | — |
| 5 | README updates (CN + EN) | `README-CN.md`, `README.md` | — |
| 6 | Design spec | `docs/specs/2026-05-11-graph-viewer-design.md` | — |
| 7 | End-to-end on real vault | `F:/whb/github/AI_stdudy/obsidian` | 255 nodes / 543 edges / 70 broken, viewer renders |

## Decisions made during implementation

- **`</script>` XSS escape** — discovered while writing the security test. `json.dumps(ensure_ascii=False)` does not escape `<` / `>` / U+2028 / U+2029, all of which can break the JSON-in-`<script>` context. Added post-serialisation string replacement before substitution into the template. Regression test asserts the escape.
- **Section deduplication within a single H2** — same wikilink appearing twice under one section now collapses to a single edge. The demo did not dedupe, which inflated the edge count.
- **`inbox` type colour** — added to the palette because `--include-inbox` was always part of the surface; `#D1D5DB` (neutral grey) signals "not yet curated".
- **Mindmap eager pre-computation** — all topic mindmaps are built in Python and shipped in the JSON payload. Avoids a second roundtrip and makes the topic picker instant. Cost: ~50 KB per topic, ~400 KB total for our 18 topics — well within budget.

## Verification

```
$ python -m pytest tests/test_graph_builder.py tests/test_graph_view.py
============================== 23 passed in 0.37s ===============================

$ python -m pytest
============================ 592 passed, 1 skipped ============================

$ python skills/obsidian/obsidian_writer.py --type graph --vault F:/whb/github/AI_stdudy/obsidian
[OK] Graph written to: _graph.html
  Nodes: 255  ·  Edges: 543 (explicit 445 / implicit 98)  ·  Broken: 70
  Open: file:///F:/whb/github/AI_stdudy/obsidian/_graph.html
```

## Follow-ups (not implemented)

- Lock highlight of currently-selected node on the canvas (currently the panel opens but the canvas only reflects hover state).
- PageRank / betweenness centrality column in the info panel and a "central topics" sort.
- Include 00-Inbox subsection of the mindmap-vault view when `--include-inbox` is set.
- Optional integration with `lint`: when lint reports orphans, suggest `--type graph` for visual triage.
