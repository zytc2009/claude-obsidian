# Compiled Knowledge Workflow Design

**Date:** 2026-04-13
**Status:** Proposed
**Scope:** Extend `claude-obsidian` from note writing into lightweight knowledge compilation

---

## 1. Goal

`claude-obsidian` already handles structured note writing well:

- capture raw material into `literature`
- write `concept`, `topic`, and `project` notes
- suggest related links
- lint and index the vault

The next gap is that the vault does not yet evolve when new material arrives.

This spec adds a minimal "compiled knowledge" layer without replacing the current Obsidian workflow. The target is not a full LLM wiki. The target is to make new material actively improve existing knowledge pages.

Four capabilities are in scope:

1. operation log
2. merge-first ingest
3. cascade updates
4. conflict annotations

---

## 2. Product Direction

The system should remain Obsidian-native and file-based.

We are not introducing a separate `raw/` + `wiki/` project structure in this phase.
We keep the existing vault layout and note types:

- `literature` = source-oriented note
- `topic` = synthesized understanding page
- `concept` = focused concept card
- `project` = practical problem/solution record

The main behavioral shift is this:

- current model: ingest writes a new note, then suggests links
- new model: ingest writes or merges a note, then updates affected knowledge pages

This is a workflow upgrade, not an architecture reset.

---

## 3. Non-Goals

Not in scope for this phase:

- introducing a separate immutable `raw/` directory
- automatic rewriting of large parts of the vault
- cross-vault graph reasoning
- automatic archiving of query answers
- embedding retrieval or vector search
- aggressive auto-link insertion across all files

The implementation should stay conservative and explainable.

---

## 4. New Concepts

### 4.1 Source lineage

Every note touched by ingest should be traceable back to the source note that caused the update.

Minimum requirement:

- `literature` notes keep explicit source metadata as they already do
- `topic` and `concept` notes gain a lightweight `source_notes` field in frontmatter or a dedicated body section

Recommended body section name:

`# Supporting notes`

Example:

```md
# Supporting notes
- [[Literature - Attention Is All You Need]]
- [[Literature - FlashAttention Survey]]
```

### 4.2 Knowledge-affecting update

A note counts as "knowledge-affecting" only when at least one of these changes:

- current conclusions
- core mechanism
- limitations or tradeoffs
- recommended practices
- conflict status

Cosmetic edits do not count.

This matters for:

- updating `updated` dates
- writing operation logs
- deciding whether cascade updates occurred

---

## 5. Operation Log

### 5.1 Purpose

Add a vault-root append-only file:

`_log.md`

This gives the user a compact answer to:

- what changed this week
- which ingest updated existing notes
- whether the system merged or created
- whether conflicts were introduced

### 5.2 Format

```md
# Vault Operation Log

## [2026-04-13] ingest | Literature - Attention Is All You Need
- Action: created
- Cascade-updated: [[Topic - Transformer Architecture]]
- Cascade-updated: [[Concept - Self-Attention]]
- Conflicts: none

## [2026-04-13] ingest | Literature - New Attention Benchmark
- Action: merged into [[Literature - Attention Is All You Need]]
- Cascade-updated: [[Topic - Transformer Architecture]]
- Conflicts: [[Topic - Transformer Architecture]]

## [2026-04-13] lint
- Broken links: 1
- Orphans: 2
- Auto-fixed: 1
```

### 5.3 Trigger Rules

Write a log entry for:

- every successful `capture`
- every successful `write` of `literature`
- every successful `organize` that creates or rewrites a `topic` or `moc`
- every `lint`
- optional later: `query --archive`

Plain `fleeting` should not log.

---

## 6. Merge-First Ingest

### 6.1 Why

Without merge-first, `literature` notes will grow linearly with sources and quickly become noisy. The system needs a first-pass decision:

- new source = same thesis, same object, more evidence -> merge
- new source = different object or distinct conceptual center -> create new note

### 6.2 Decision Order

When a new source is captured into a `literature` note:

1. search existing `literature` notes by title keywords
2. search existing `topic` notes for the same conceptual center
3. compare the new source against the best candidate literature note
4. choose one of:
   - `create`
   - `merge`
   - `create + cascade`

### 6.3 Merge Criteria

Merge only when most of the following are true:

- same primary subject
- same core claim or thesis
- same comparison target or problem framing
- new source mainly adds evidence, examples, benchmarks, or nuance

Do not merge when any of these are true:

- different primary question
- distinct concept deserves separate retrieval later
- title overlap is superficial
- the new source would make the destination note too heterogeneous

### 6.4 Merge Behavior

If merge is selected:

- append the new source to a `sources` list
- integrate new facts into the relevant sections
- preserve the original note title unless it is clearly too narrow
- refresh `updated`
- emit an operation log entry with `Action: merged`

### 6.5 Minimal Data Model Change

Recommended frontmatter additions for `literature`:

```yaml
source_count: 2
source_notes: []
```

If frontmatter expansion is undesirable, use body sections:

- `# Sources`
- `# Change notes`

---

## 7. Cascade Updates

### 7.1 Why

This is the highest-value change. A new source should not only create or merge one note. It should also update nearby synthesis pages so the vault compounds over time.

### 7.2 Scope

Phase 1 cascade should be intentionally narrow.

Allowed targets:

- `topic` notes with strong title/body match
- `concept` notes explicitly mentioned by the new literature note

Do not update in phase 1:

- unrelated `project` notes
- all notes in the vault
- notes with only weak lexical overlap

### 7.3 Update Order

After ingest finishes its primary target:

1. identify directly related `topic` notes
2. identify directly related `concept` notes
3. update only the sections materially affected
4. add the new supporting literature link
5. refresh `updated`
6. record touched files in `_log.md`

### 7.4 Allowed Section-Level Changes

For `topic`:

- `当前结论`
- `重要资料`
- `未解决问题`

For `concept`:

- `核心机制`
- `局限`
- `适用场景`
- `相关链接`

Avoid rewriting the whole note unless the old structure is obviously broken.

### 7.5 Threshold

Cascade only when there is clear evidence that the new source changes knowledge, not merely mentions similar words.

Good triggers:

- adds a better explanation
- adds a new benchmark or boundary
- resolves an open question
- introduces a contradiction

Bad triggers:

- repeated summary of known content
- keyword-only overlap
- tangential mention

---

## 8. Conflict Annotations

### 8.1 Purpose

When a new source disagrees with existing notes, the disagreement should become explicit instead of silently overwriting old content.

### 8.2 Conflict Types

The system only needs lightweight conflict tracking in this phase:

- conclusion conflict
- metric conflict
- mechanism conflict
- recommendation conflict

### 8.3 Representation

Recommended body section:

```md
# Conflicts
- Source: [[Literature - New Attention Benchmark]]
  Claim: FlashAttention no longer dominates on small-sequence inference.
  Conflicts with: [[Literature - FlashAttention Survey]]
  Status: unresolved
```

If nested bullets feel too heavy in the templates, use one paragraph per conflict item instead.

### 8.4 Rules

When conflict is detected:

- do not delete the older claim automatically
- add source-attributed disagreement
- update the affected `topic` if the disagreement changes synthesized conclusions
- write the conflict target into `_log.md`

### 8.5 Detection Standard

Conflict detection should be conservative.

Only annotate when disagreement is concrete, such as:

- opposite recommendation
- materially different benchmark result
- incompatible explanation of mechanism

Do not mark "different emphasis" as conflict.

---

## 9. Minimal Script Changes

The current script is deterministic and does not perform ingest reasoning itself. That separation should remain.

### 9.1 Keep

- `obsidian_writer.py` remains responsible for file I/O, templates, lint, index, and deterministic helpers
- skill prompt remains responsible for intent detection and content extraction

### 9.2 Add to Script

Deterministic helpers only:

- append to `_log.md`
- update `sources` or `supporting notes` sections
- find candidate notes by title/body keyword match
- patch limited note sections

### 9.3 Keep Out of Script

LLM judgment should stay outside the script:

- merge vs create decision
- whether a conflict exists
- whether a cascade update is knowledge-affecting

This preserves testability.

---

## 10. Phased Rollout

### Phase 1

- create `_log.md`
- log `capture`, `write(literature)`, `organize`, and `lint`
- add supporting-note section conventions

### Phase 2

- implement merge-first decision in skill workflow
- support source appends in `literature`
- update tests for merge behavior

### Phase 3

- implement same-topic cascade updates for `topic`
- log touched notes

### Phase 4

- extend cascade to `concept`
- add conflict annotation support

### Phase 5

- refine heuristics
- add dry-run preview for merge/cascade actions

---

## 11. UX Requirements

The user should see explicit action summaries after ingest.

Example:

```text
[OK] Captured into: 03-Knowledge/Literature/Literature - Attention Is All You Need.md
[Action] merged
[Cascade updates]
  -> Topic - Transformer Architecture
  -> Concept - Self-Attention
[Conflicts]
  none
```

If confidence is low, the workflow should fall back to create-only behavior rather than risky merge/update.

---

## 12. Acceptance Criteria

This spec is successful when:

1. a new source can be logged without changing existing note behavior
2. repeated sources on the same thesis no longer always create new literature notes
3. ingest can update at least one existing `topic` note in a narrow, explainable way
4. concrete disagreements can be surfaced without overwriting old claims
5. users can audit recent vault changes from `_log.md`

---

## 13. Design Summary

The right next step for `claude-obsidian` is not to become a full Karpathy-style wiki.

The right next step is smaller:

- keep the current vault and note model
- add merge-first behavior
- add narrow cascade updates
- add explicit conflict handling
- add an operation log

That is enough to move from "AI writes notes for me" toward "AI helps maintain my knowledge base."
