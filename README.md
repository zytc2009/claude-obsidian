# obsidian-connector

A Claude Code skill that writes structured notes directly into your local Obsidian vault — no copy-pasting, no manual formatting.

## Overview

`obsidian-connector` bridges Claude Code sessions and Obsidian. You can capture fleeting thoughts, archive web articles, log conversations as notes, merge related notes into topic summaries, query your knowledge base, and keep your vault healthy — all from natural language or `/obsidian`.

**Architecture:**
```
Claude Code Skill (SKILL.md)      — intent detection, field extraction
        ↓
obsidian_writer.py                — template rendering, file I/O (no LLM calls)
        ↓
Your Obsidian Vault
  ├── 00-Inbox/                   ← draft / incomplete notes
  ├── 01-DailyNotes/              ← fleeting notes appended here
  ├── 02-Projects/                ← project pages
  ├── 03-Knowledge/
  │   ├── Concepts/               ← concept cards
  │   ├── Literature/             ← article / paper notes
  │   ├── MOCs/                   ← maps of content
  │   └── Topics/                 ← topic summaries
  └── 04-Archive/                 ← archived notes
  └── _log.md                     ← append-only operation log
```

## Operations

### `fleeting` — Quick capture

Append a timestamped idea to today's daily note in one step.

```
Note down: using MOCs to organize cross-topic note links
Thought: #rag context window impact on recall@5 is worth testing
```

Appends to `01-DailyNotes/YYYY-MM-DD.md` under a `# Fleeting` section. Creates the daily note if it does not exist.

### `capture` — Archive a URL or file

Fetch a web page or read a local file, then write a dense `literature` note preserving ~80% of the source's information.

```
/obsidian capture https://example.com/article
/obsidian capture C:/Downloads/paper.md
```

### `log` — Turn a conversation into a note

Analyze the current conversation and write it as a structured note. The note type is auto-detected:

| Conversation content | Note type |
|----------------------|-----------|
| Research or learning | `literature` |
| Deep topic discussion | `topic` |
| Project planning | `project` |
| Concept breakdown | `concept` |

```
/obsidian log this conversation
```

### `write` — Structured note creation

Write any note type explicitly:

| Trigger | Type |
|---------|------|
| article, paper, blog, research note | `literature` |
| concept, concept card | `concept` |
| topic, topic page | `topic` |
| project, project page | `project` |

### `organize` — Search, merge, archive

Search the vault for related notes, merge them into a `topic` or `MOC`, and surface Inbox notes ready for filing.

```
/obsidian organize RAG
```

### Topic discovery

After writing a note, the script can surface:

- `[Link suggestions]`: existing `topic` matches first, then `MOC` matches
- explainable reasons such as `strength=high`, `title=...`, or `body=...`
- `[Topic suggestion]`: a conservative hint to create a new `topic` when no strong existing topic match is found

This is meant to help you discover where a note belongs, not to aggressively auto-link everything.

### `query` — Query your knowledge base

Search existing notes and answer questions with citations. Optionally archive the answer as a new topic note.

```
/obsidian query what do my notes say about RAG?
在我笔记里查一下 Transformer 的局限性
```

Retrieval is two-tier:

- **Tier 1 (default):** scan only `topic` notes; compose the answer from `主题说明`, `当前结论`, `未解决问题` with per-claim citations.
- **Tier 2 (on request):** if no topic matches, or when you ask "展开" / "细节", surface literature and project hits grouped under their parent topic. Orphan hits (notes with no topic parent) are reported in a separate section so fragmentation is visible on every query.

Each claim in the answer is cited back to its source note: `answer text — [[Concept - Self-Attention]]`.

### `lint` — Vault health check

Scan the vault for quality issues and optionally auto-fix simple ones.

```
/obsidian lint
/obsidian lint --auto-fix
```

| Check | Description | Action |
|-------|-------------|--------|
| Broken links | `[[wikilinks]]` pointing to non-existent notes | Reported |
| Orphan notes | Knowledge/Projects notes not referenced from any MOC/Topic | Reported |
| Inbox backlog | Notes stuck in `00-Inbox` for more than 7 days | Reported |
| Skeleton notes | Notes with more than 50% `_placeholder_` fields | Reported |
| Stale notes | Active notes not updated in 90+ days | Reported |
| Stale synthesis | Topic notes whose linked literature was updated 30+ days after the topic | Reported |
| Missing frontmatter | Notes lacking `status`/`created`/`updated` | Auto-fixed with `--auto-fix` |

Detected issues are appended to `_corrections.jsonl` as machine-readable correction events (`resolved: false`). When you fix an issue manually, the next lint run will not re-emit it.

Example output:
```
[Lint] Scanned 47 notes in ~/obsidian/

[Broken links] (1)
⚠ 03-Knowledge/MOCs/MOC - AI Learning.md → [[Concept - GPT5]]

[Orphan notes] (2)
⚠ 03-Knowledge/Concepts/Concept - LoRA.md
⚠ 03-Knowledge/Literature/Literature - RAG Survey.md

[Inbox backlog] (1)
⚠ 00-Inbox/Literature - Some Draft.md (11 days old)
```

### `topic-scout` — Cluster orphan notes and propose topics

Scan `00-Inbox/` and `03-Knowledge/` for notes without a topic parent, cluster them by shared vocabulary, and propose topic candidates.

```
/obsidian topic-scout
```

Example output:

```
[Topic Scout] Scanned 6 orphan note(s)

Found 2 cluster(s) — consider creating a topic for each:

Cluster 1 (3 notes) → suggested: Topic - Harness Engineering
  [[Literature - Harness Engineering 最佳実践]]
  [[Literature - Harness Engineering与Agents编排]]
  [[Literature - 一文读懂Harness Engineering]]

Singletons (1 note(s) with no close match):
  [[Literature - RAG Survey 2024]]
```

User picks which clusters to materialize as topic notes. Runs on demand, not automatically.

### `index` — Rebuild knowledge index

Rebuild `_index.md` at the vault root — a global navigation page listing all notes by section with summaries and dates. New notes are added to the index automatically after every `write` or `capture`.

```
/obsidian index
```

### `suggestion-feedback` — Record suggestion feedback

Record an explicit rejection or modified acceptance of a link/topic/merge/cascade suggestion. This feeds into future link-suggestion ranking without touching note content.

```bash
python skills/obsidian/obsidian_writer.py \
  --type suggestion-feedback \
  --source-note "Literature - RAG Survey" \
  --suggestion-type link \
  --feedback-action reject \
  --targets "03-Knowledge/Topics/Topic - LLM.md" \
  --reason "wrong topic, RAG is not an LLM concern"
```

Events are stored in `_events.jsonl`. Supported `--feedback-action` values: `reject`, `modify-accept`.

### `merge-candidates` — Find likely merge targets

Surface existing `literature` notes whose title/body overlap enough to be considered merge-first candidates during ingest.

```bash
python skills/obsidian/obsidian_writer.py \
  --type merge-candidates \
  --title "Attention Survey"
```

### `merge-update` — Merge into an existing note

After the model decides a new source should update an existing `literature` note instead of creating a new one, use `merge-update` to replace the chosen sections and attach source lineage.

```bash
python skills/obsidian/obsidian_writer.py \
  --type merge-update \
  --target "03-Knowledge/Literature/Literature - Attention Is All You Need.md" \
  --fields '{"核心观点": "...", "方法要点": "..."}' \
  --source-note "Literature - Attention Survey" \
  --source-ref "OpenAI, 2026-04-13"
```

This also refreshes the note's `updated` frontmatter field.

### `cascade-candidates` — Find likely topic pages to refresh

After a source note is created or merged, surface matching `topic` pages that may need a narrow synthesis update.

```bash
python skills/obsidian/obsidian_writer.py \
  --type cascade-candidates \
  --target "03-Knowledge/Literature/Literature - Attention Survey.md"
```

### `cascade-update` — Narrow topic update

Apply a conservative update to an existing `topic` note. This command only accepts topic-level synthesis fields.

```bash
python skills/obsidian/obsidian_writer.py \
  --type cascade-update \
  --target "03-Knowledge/Topics/Topic - Attention Mechanism.md" \
  --fields '{"当前结论": "...", "重要资料": "[[Literature - Attention Survey]]"}' \
  --source-note "Literature - Attention Survey"
```

This also refreshes the topic note's `updated` frontmatter field.

### `conflict-update` — Add an explicit conflict annotation

When a new source concretely disagrees with an existing note, append a structured entry under `# Conflicts` instead of silently overwriting the older claim.

```bash
python skills/obsidian/obsidian_writer.py \
  --type conflict-update \
  --target "03-Knowledge/Topics/Topic - Attention Mechanism.md" \
  --fields '{"claim": "New benchmark reverses the old conclusion."}' \
  --source-note "Literature - New Benchmark" \
  --conflicts-with "[[Literature - FlashAttention Survey]]"
```

When a new conflict entry is added, the target note's `updated` field is refreshed.

### `ingest-sync` — Apply a full deterministic ingest plan

If the model has already decided the primary update, cascade updates, and conflict annotations, it can send the whole plan in one call instead of invoking multiple subcommands.

```bash
python skills/obsidian/obsidian_writer.py \
  --type ingest-sync \
  --target "03-Knowledge/Literature/Literature - Attention Survey.md" \
  --fields '{
    "primary_fields": {"核心观点": "..."},
    "source_note": "Literature - New Benchmark",
    "source_ref": "OpenAI, 2026-04-13",
    "cascade_updates": [
      {
        "target": "03-Knowledge/Topics/Topic - Attention Mechanism.md",
        "fields": {"当前结论": "..."}
      }
    ],
    "conflicts": [
      {
        "target": "03-Knowledge/Topics/Topic - Attention Mechanism.md",
        "claim": "New benchmark reverses the old conclusion.",
        "conflicts_with": "[[Literature - FlashAttention Survey]]"
      }
    ]
  }'
```

### `init` — Initialize vault structure

Create all required directories on first use, then print the resulting tree as confirmation. Safe to re-run — skips directories that already exist.

```
/obsidian init
```

Example output:

```
[OK] Created 8 directories:
  + 00-Inbox/
  + 01-DailyNotes/
  ...

~/obsidian/
├── 00-Inbox/
├── 01-DailyNotes/
├── 02-Projects/
├── 03-Knowledge/
│   ├── Concepts/
│   ├── Literature/
│   ├── MOCs/
│   └── Topics/
└── 04-Archive/
```

## Observability

Two machine-readable event streams are maintained at the vault root:

| File | Purpose |
|------|---------|
| `_corrections.jsonl` | Quality issues found by `lint` — broken links, orphan notes, stale synthesis, etc. Each line: `{ts, note, issue_type, detail, detected_by, resolved}` |
| `_events.jsonl` | Explicit suggestion feedback (reject / modify-accept). Each line: `{ts, event_type, suggestion_type, source_note, target_notes, action, reason}` |

`_log.md` is the human-readable activity log. When it exceeds 500 entries, older entries rotate into `_log.archive.md`.

Link suggestions consult `_events.jsonl` to down-rank previously rejected targets (per source note). The lexical matching heuristic remains the primary ranking signal.

## Note Types

### Literature — Article / paper notes

Dense notes designed so you can recall 80% of the source weeks later without re-reading it.

Key fields: `core ideas` (full argument chain with why and how), `method details` (steps, numbers, thresholds, examples), `main content` (section-by-section reconstruction), `details` (data points, quotes, surprising facts), `concepts to extract`, `knowledge links`

### Concept — Concept cards

One focused page per concept, extracted from literature or discussions.

Key fields: `one-line definition`, `core mechanism`, `advantages`, `limitations`, `use cases`, `common misconceptions`

### Topic — Topic summaries

A synthesis page that organizes your current understanding of a theme across literature and project notes.

Key fields: `topic description`, `core question`, `current conclusions`, `key references`, `related projects`, `open questions`

### Project — Problem and solution records

A lightweight page for practical work notes: what happened, why it happened, how you investigated it, and how you solved it.

Key fields: `project description`, `root cause analysis`, `investigation process`, `solution`, `validation`, `risks and open issues`

## Draft routing

A note is automatically routed to `00-Inbox/` when:

- You explicitly say "draft" or "save to inbox"
- Fewer than half of the required fields could be filled

Required fields per type:

| Type | Required fields |
|------|----------------|
| `literature` | core ideas, method details |
| `concept` | one-line definition, core mechanism |
| `topic` | topic description, current conclusions |
| `project` | project description, investigation process, solution |

## Installation

The repo serves **Claude Code / Codex / WorkBuddy** via `install.py --target`:

```bash
git clone https://gitcode.com/landuochong/claude-obsidian.git obsidian-connector
cd obsidian-connector

python install.py --target claude      # Claude Code (default)
python install.py --target codex       # Codex
python install.py --target workbuddy   # WorkBuddy (auto-adapted: NL triggers, python3, local vault path)
python install.py --target all         # all three
```

**Configure your vault path** (default: `~/obsidian/`; scripts don't expand `~`, use an absolute path or env var):

```bash
export OBSIDIAN_VAULT_PATH=/path/to/your/vault
python obsidian_writer.py --vault /path/to/vault ...   # or pass --vault
```

**Requirements:** Python 3.9+, zero third-party deps. Pick any one of Claude Code / Codex / WorkBuddy.

## Share / Publish to the Skill Marketplace

Don't want others to clone? Package it as a one-click WorkBuddy skill:

```bash
python sync_workbuddy.py --pack   # -> dist/obsidian-skill.zip (no personal paths baked in)
```

Then publish at [WorkBuddy Open Platform](https://open.workbuddy.cn):
1. Register + developer verification (personal account is fine, no coding required).
2. **Publish Management → New Skill**, upload `dist/obsidian-skill.zip`, fill name / category / description.
3. Submit for review (3 parallel pipelines: content compliance + vulnerability scan + model safety; usually <24h in beta).
4. Once approved, **list it** — others install by searching the name in WorkBuddy.

> Want to charge? After ≥1 free skill is approved, enable payout in "收入变现", then switch to paid (one-time / subscription — **locked after publish**).
>
> Packaging rules: skill `name` only lowercase/digits/hyphens; `description` no angle brackets; no hardcoded secrets or personal absolute paths (this repo handles all of that).

## Script reference

`obsidian_writer.py` is a standalone CLI with no LLM dependency — useful for testing and scripting outside Claude Code.

```bash
# Write a note
python skills/obsidian/obsidian_writer.py \
  --type literature \
  --title "Attention Is All You Need" \
  --fields '{"核心观点": "...", "方法要点": "..."}' \
  --draft false

# Write a note and attach lineage/source metadata
python skills/obsidian/obsidian_writer.py \
  --type topic \
  --title "RAG" \
  --fields '{"主题说明": "...", "当前结论": "..."}' \
  --source-note "Literature - RAG Survey" \
  --source-ref "Anthropic, 2026-04-13"

# Append a fleeting note
python skills/obsidian/obsidian_writer.py \
  --type fleeting \
  --fields '{"content": "interesting idea", "tags": "#ai"}'

# Initialize vault directories (first-time setup)
python skills/obsidian/obsidian_writer.py --type init

# Vault health check (report only)
python skills/obsidian/obsidian_writer.py --type lint

# Vault health check with auto-fix (repairs missing frontmatter)
python skills/obsidian/obsidian_writer.py --type lint --auto-fix

# Rebuild global index (_index.md)
python skills/obsidian/obsidian_writer.py --type index

# Render interactive knowledge-graph + mindmap viewer (single HTML)
python skills/obsidian/obsidian_writer.py --type graph
python skills/obsidian/obsidian_writer.py --type graph --topic "Topic - RAG"
python skills/obsidian/obsidian_writer.py --type graph --filter-type topic
python skills/obsidian/obsidian_writer.py --type graph --include-inbox

# Find literature notes that may be merge targets
python skills/obsidian/obsidian_writer.py --type merge-candidates --title "Attention Survey"

# Merge updated synthesis into an existing literature note
python skills/obsidian/obsidian_writer.py \
  --type merge-update \
  --target "03-Knowledge/Literature/Literature - Attention Is All You Need.md" \
  --fields '{"核心观点": "...", "方法要点": "..."}' \
  --source-note "Literature - Attention Survey" \
  --source-ref "OpenAI, 2026-04-13"

# Find topic notes that may need a cascade update
python skills/obsidian/obsidian_writer.py \
  --type cascade-candidates \
  --target "03-Knowledge/Literature/Literature - Attention Survey.md"

# Apply a narrow cascade update to a topic note
python skills/obsidian/obsidian_writer.py \
  --type cascade-update \
  --target "03-Knowledge/Topics/Topic - Attention Mechanism.md" \
  --fields '{"当前结论": "...", "重要资料": "[[Literature - Attention Survey]]"}' \
  --source-note "Literature - Attention Survey"

# Add an explicit conflict annotation
python skills/obsidian/obsidian_writer.py \
  --type conflict-update \
  --target "03-Knowledge/Topics/Topic - Attention Mechanism.md" \
  --fields '{"claim": "New benchmark reverses the old conclusion."}' \
  --source-note "Literature - New Benchmark" \
  --conflicts-with "[[Literature - FlashAttention Survey]]"

# Apply the whole ingest plan in one call
python skills/obsidian/obsidian_writer.py \
  --type ingest-sync \
  --target "03-Knowledge/Literature/Literature - Attention Survey.md" \
  --fields '{"primary_fields":{"核心观点":"..."},"source_note":"Literature - New Benchmark","source_ref":"OpenAI, 2026-04-13","cascade_updates":[{"target":"03-Knowledge/Topics/Topic - Attention Mechanism.md","fields":{"当前结论":"..."}}],"conflicts":[{"target":"03-Knowledge/Topics/Topic - Attention Mechanism.md","claim":"New benchmark reverses the old conclusion.","conflicts_with":"[[Literature - FlashAttention Survey]]"}]}'

# Cluster orphan notes and propose topic candidates
python skills/obsidian/obsidian_writer.py --type topic-scout

# Record a rejected link suggestion
python skills/obsidian/obsidian_writer.py \
  --type suggestion-feedback \
  --source-note "Literature - RAG Survey" \
  --suggestion-type link \
  --feedback-action reject \
  --targets "03-Knowledge/Topics/Topic - LLM.md"

# Dry-run: preview without writing
python skills/obsidian/obsidian_writer.py --type topic --title "RAG" \
  --fields '{}' --dry-run
```

## Development

```bash
# Run tests
python -m pytest

# Run with coverage
python -m pytest --cov=scripts
```

The test suite covers all note types, fleeting append logic, draft routing, filename collision handling, lint checks, link suggestions, index generation, observability streams, orphan-on-create tracking, topic-scout clustering, stale-synthesis detection, and the CLI (137 tests).

## File naming

All notes follow the pattern `{Prefix} - {Title}.md`. If a file with the same name already exists, today's date is appended: `Literature - Title 2026-04-07.md`.
