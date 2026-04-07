# claude-obsidian

A Claude Code skill that writes structured notes directly into your local Obsidian vault — no copy-pasting, no manual formatting.

## Overview

`claude-obsidian` bridges Claude Code sessions and Obsidian. You can capture fleeting thoughts, archive web articles, log conversations as notes, and merge related notes into topic summaries — all from natural language or `/obsidian`.

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

D:/obsidian/
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

## Note Types

### Literature — Article / paper notes

Dense notes designed so you can recall 80% of the source weeks later without re-reading it.

Key fields: `core ideas` (full argument chain with why and how), `method details` (steps, numbers, thresholds, examples), `main content` (section-by-section reconstruction), `details` (data points, quotes, surprising facts), `concepts to extract`, `knowledge links`

### Concept — Concept cards

One focused page per concept, extracted from literature or discussions.

Key fields: `one-line definition`, `core mechanism`, `advantages`, `limitations`, `use cases`, `common misconceptions`

### Topic — Topic summaries

A synthesis page aggregating concepts, literature, and open questions around a theme.

### Project — Project pages

Project tracking with goals, tasks, risk assessment, and an embedded experiment log section.

## Draft routing

A note is automatically routed to `00-Inbox/` when:

- You explicitly say "draft" or "save to inbox"
- Fewer than half of the required fields could be filled

Required fields per type:

| Type | Required fields |
|------|----------------|
| `literature` | core ideas, method details |
| `concept` | one-line definition, core mechanism |
| `topic` | topic description, core concepts |
| `project` | goal, completion criteria, task breakdown |

## Installation

```bash
git clone https://github.com/your-username/claude-obsidian.git
cd claude-obsidian
python install.py
```

This copies `skills/obsidian/obsidian_writer.py` to `~/.claude/scripts/` and `skills/obsidian/` to `~/.claude/skills/obsidian/`.

**Configure your vault path** (default: `./obsidian`):

```bash
# Option 1: environment variable
export OBSIDIAN_VAULT_PATH=/path/to/your/vault

# Option 2: pass --vault at call time
python obsidian_writer.py --vault /path/to/vault ...
```

**Requirements:** Python 3.9+, Claude Code

## Script reference

`obsidian_writer.py` is a standalone CLI with no LLM dependency — useful for testing and scripting outside Claude Code.

```bash
# Write a note
python skills/obsidian/obsidian_writer.py \
  --type literature \
  --title "Attention Is All You Need" \
  --fields '{"core ideas": "...", "method details": "..."}' \
  --draft false

# Append a fleeting note
python skills/obsidian/obsidian_writer.py \
  --type fleeting \
  --fields '{"content": "interesting idea", "tags": "#ai"}'

# Initialize vault directories (first-time setup)
python skills/obsidian/obsidian_writer.py --type init

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

The test suite covers all note types, fleeting append logic, draft routing, filename collision handling, and the CLI.

## File naming

All notes follow the pattern `{Prefix} - {Title}.md`. If a file with the same name already exists, today's date is appended: `Literature - Title 2026-04-07.md`.
