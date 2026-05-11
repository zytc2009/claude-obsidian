# Graph viewer — design spec

**Date:** 2026-05-11
**Status:** implemented
**Modules:** `skills/obsidian/graph_builder.py`, `skills/obsidian/graph_view.py`
**CLI:** `python obsidian_writer.py --type graph`

## Problem

The vault already exposes structure through `_index.md` (flat list per type) and through wikilinks in note bodies, but neither makes the **topology** legible. Specifically the user wants to answer:

- Which topics are central? Which are isolated?
- What does a single topic actually pull together — which literature, projects, concepts?
- Which laid-down links are broken?
- Where does the type distribution skew (too many literature, too few concepts)?

Obsidian ships a graph view but it doesn't read our `frontmatter.type`, `frontmatter.topic`, or H2 section semantics. So it cannot colour by note type, dim drafts, separate explicit vs implicit edges, or surface key fields on hover.

## Goals

1. Render the vault as an interactive single-file HTML viewer.
2. Four selectable views: graph (force-directed), ego (one-topic radial), mindmap-topic (radial tree), mindmap-vault (radial tree by type).
3. Click a node → persistent right-side info panel with type-specific key fields, link distribution, and Obsidian jump button.
4. Zero new Python dependencies; D3 from CDN with SRI hash for tamper detection.
5. Output goes to `<vault>/_graph.html` by default.

## Non-goals

- Live updating. The HTML is a snapshot; re-run to refresh.
- Two-way editing. The viewer is read-only — wikilink-copy and `obsidian://` are the only escape hatches back to Obsidian.
- LLM-derived relations. The graph is built strictly from `[[wikilinks]]` and `frontmatter.topic`; no semantic extraction.

## Data model

```
GraphNode
  id, type, title, summary, status,
  updated, created, tags, author, source, rel_path,
  in_degree, out_degree,
  section_contents: { H2-name → first 600 chars },
  backlinks: [{from, section, kind}] (cap 8),
  forwardlinks_by_section: { section → [target stems] },
  backlinks_total

GraphEdge
  source, target, section, kind  ("explicit" | "implicit")

VaultGraph
  nodes, edges, broken (referenced-but-not-found stems), topics
```

Two edge kinds:

- **explicit** — `[[wikilink]]` in note body, attributed to the H2 section it appears in.
- **implicit** — frontmatter `topic: [X]` entry, attributed to `_frontmatter` and rendered as a dashed line in the UI.

## Scope rules

- Scan `INDEX_DIRS` from `index.py` (Topics / MOCs / Concepts / Literature / Projects / Articles).
- `00-Inbox` is excluded by default — opt in with `--include-inbox`.
- Notes with `status: draft` are excluded so the graph stays high-signal.
- Self-links are dropped.
- Within a single section, duplicate wikilinks collapse to one edge.

## Node type colour palette

Tailwind-derived for legibility on light background:

| Type | Face | Ring |
|---|---|---|
| topic | `#FB923C` | `#EA580C` |
| literature | `#60A5FA` | `#2563EB` |
| concept | `#34D399` | `#059669` |
| project | `#A78BFA` | `#7C3AED` |
| moc | `#94A3B8` | `#475569` |
| article | `#F87171` | `#DC2626` |
| inbox | `#D1D5DB` | `#9CA3AF` |

## Info panel — type-specific key fields

The panel is the load-bearing UI element. To respect each note type's semantics, a curated `KEY_FIELDS` mapping decides which H2 sections get pulled into the highlighted yellow cards at the top of the panel:

```
topic       → 主题说明 / 核心问题 / 当前结论 / 未解决问题
literature  → 这份资料试图解决什么问题 / 解决的问题 / 核心观点 / 方法要点
concept     → 一句话定义 / 核心机制 / 适用场景 / 我的理解
project     → 项目描述 / 解决方案 / 风险与遗留问题 / 结果验证
article     → 核心论点 / 结语
```

Remaining sections collapse under "📖 其他区块正文 (n)".

## Security

- D3 is pinned with `integrity="sha384-..."` and `crossorigin="anonymous"`. Bumping the CDN version requires regenerating the hash.
- User content embedded in the `<script>` block escapes `</` → `<\/`, `<!--` → `<\!--`, U+2028 and U+2029 (JS string-terminator characters that JSON does not escape). This is the canonical mitigation for the JSON-in-script context. A regression test in `test_graph_view.py` asserts the escape is in place.
- All user content rendered into the DOM goes through an `escapeHTML` helper. No `innerHTML` paths accept unsanitised data.

## CLI surface

```
--type graph                        # default: write <vault>/_graph.html
--output PATH                       # override output path
--filter-type {topic|literature|...}# pre-select a single type in the filter UI
--topic STEM                        # initial topic for ego / mindmap-topic
--include-inbox                     # include 00-Inbox notes
```

The CLI keeps all existing flags backward-compatible.

## Failure modes

- **Missing topic mindmap** — if a topic's `build_topic_mindmap` raises, the viewer ships an empty stub for that topic and the rest of the viewer still works.
- **Broken links** — referenced stems that don't resolve appear in `graph.broken`. The info panel surfaces them with a "断" badge so the user can fix or remove them.
- **No topics** — `default_topic` falls back to empty string; ego/mindmap-topic views show "(no content)".

## Tests

- `tests/test_graph_builder.py` — 14 tests covering scan boundaries, draft exclusion, edge classification, self-link suppression, section truncation, backlinks/forwardlinks correctness, and mindmap shape.
- `tests/test_graph_view.py` — 9 tests covering output paths, required DOM ids, embedded JSON validity, SRI hash presence, default-topic selection, and the `</script>`-escape XSS regression.
