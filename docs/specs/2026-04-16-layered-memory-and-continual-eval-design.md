# Layered Memory And Continual Eval Design

**Date:** 2026-04-16
**Status:** Draft
**Scope:** Add a session-memory layer, elevate `topic` notes into a middle memory layer, and introduce continual-memory evaluation for `claude-obsidian`

---

## 1. Problem

`claude-obsidian` already has two useful memory primitives:

- the vault as the authoritative long-term knowledge store
- `_memory.jsonl` as a lightweight activation-based hot cache

That is a good start, but it still leaves three gaps.

### 1.1 No explicit working memory

The current memory model knows what was active recently across sessions, but it does not explicitly track what is active in the current conversation or task.

This creates weak continuity for multi-turn work:

- the agent may re-discover the same topic repeatedly
- recent drill-down decisions are not preserved cleanly
- suggestion rejection history in the current session is not surfaced as first-class context

### 1.2 `topic` is a note type, not yet a memory layer

The existing retrieval direction is already topic-first, but `topic` notes are still treated mostly as one content type among several.

That is not enough to fight fragmentation. The system needs a clearer hierarchy:

- raw notes hold details
- topic notes hold synthesized understanding
- activation memory decides what to preload

### 1.3 No rigorous forgetting evaluation

The memory system has activation, decay, and consolidation logic, but no repeatable way to answer:

- does a newly learned concept become easier to retrieve?
- do high-frequency concepts persist better than low-frequency ones?
- does new activity interfere with older but still important knowledge?

Without those checks, memory behavior remains plausible but unverified.

---

## 2. Goal

Turn the current two-part memory setup into a layered memory system with explicit evaluation.

Concretely:

- add a session-scoped working-memory layer
- make `topic` notes the canonical mid-layer synthesis surface
- keep `_memory.jsonl` as a hot activation index, not a knowledge store
- add a deterministic continual-memory test harness for recall, decay, and interference

This design does **not** add:

- PyTorch or model-training dependencies
- embedding/vector retrieval in v1 of this change
- automatic topic synthesis rewriting without explicit write/update flows

---

## 3. Target Memory Model

The system should expose four practical layers:

| Layer | Storage | Lifetime | Purpose |
|---|---|---|---|
| Session working memory | process memory or `_session_memory.json` | current session | track current focus, recent expansions, recent rejections, active task state |
| Activation memory | `_memory.jsonl` | cross-session, decaying | rank what concepts should be surfaced quickly |
| Synthesis memory | `Topic - *.md` | long-lived | store current integrated understanding of a subject |
| Source memory | literature / concept / project notes | long-lived | preserve raw details, evidence, and implementation history |

Principle:

- lower layers preserve detail
- middle layers preserve synthesis
- upper layers preserve relevance

---

## 4. Session Working Memory

Add a new `session memory` layer between agent interaction and `_memory.jsonl`.

### 4.1 Why this layer exists

Current short-term memory in `memory_manager.py` is mostly an internal activation counter used for later consolidation. It is not a structured representation of current task state.

The new layer should instead answer:

- what topic is the user actively working on right now?
- which notes were expanded in this session?
- which suggestions were rejected in this session?
- which unresolved question is currently in focus?

### 4.2 Proposed data model

Session state should be lightweight and deterministic. A single object is enough:

```json
{
  "session_id": "2026-04-16T14:30:00",
  "active_topics": ["Topic - Harness Engineering"],
  "active_notes": [
    "Literature - Attention Survey.md",
    "Topic - Attention Mechanism.md"
  ],
  "recent_queries": ["attention limits", "topic stale synthesis"],
  "rejected_targets": {
    "Literature - Attention Survey": [
      "Topic - LLM.md"
    ]
  },
  "open_loops": [
    "decide whether to merge or create a new topic"
  ],
  "updated_at": "2026-04-16T14:42:10"
}
```

### 4.3 Storage choice

Implementation should support one practical representation first:

- default: in-process memory object
- optional persistence: vault-level `_session_memory.json`

The file should be treated as operational cache, not source of truth. It may be overwritten between sessions.

### 4.4 Read-path use

When handling `query`, `organize`, `capture`, or suggestion workflows:

1. consult session memory first
2. consult activation memory second
3. consult topic/source notes last

This reduces repeated vault scanning and improves local continuity.

### 4.5 Write-path use

Update session memory on these events:

- a query hits or expands a topic
- a note is opened for drill-down
- a suggestion is rejected or modified
- a new note is attached to a topic

This gives the system a notion of current momentum without polluting long-term memory.

---

## 5. `Topic` As Synthesis Memory

`topic` notes should become the explicit middle layer of the memory stack.

### 5.1 Role change

Today, `topic` notes are already retrieval-preferred. This design makes that role structural:

- source notes are evidence
- topic notes are synthesis
- activation memory points toward the right topics

### 5.2 Retrieval rule

The default answer path should continue to prefer `topic` notes, but with a stronger contract:

- if a topic exists, answer from the topic first
- if only source notes exist, surface them as unlinked fragments or topic candidates
- if multiple topics match, rank them by a combination of lexical relevance, activation score, and session recency

### 5.3 Memory linking rule

Activation entries in `_memory.jsonl` should be able to refer not only to source notes, but also to a parent topic.

Proposed additive fields:

```json
{
  "word": "Attention",
  "obsidian_links": [
    "Literature - Attention Survey.md"
  ],
  "topic_links": [
    "Topic - Attention Mechanism.md"
  ]
}
```

This is intentionally additive. Existing entries remain valid.

### 5.4 Consolidation behavior

When a source note is linked or merged into a topic:

- refresh activation for the source concepts
- add or refresh the parent topic link in matching activation entries
- prefer the topic during future query/context formatting

This makes the memory system converge toward synthesized nodes over time.

---

## 6. Activation Memory Adjustments

`_memory.jsonl` should remain lightweight. It should not become a duplicate mini knowledge base.

Recommended changes:

- keep current activation, decay, and pruning rules
- add optional `topic_links`
- optionally track `last_session_activated`
- format context to prefer top active topics first, then supporting concepts

Example context shape:

```text
<active_memory>
● Topic - Attention Mechanism (topic, 0.88)
  from: Attention, FlashAttention, KV cache
● Attention (concept, 0.79)
  -> [[Literature - Attention Survey.md]]
</active_memory>
```

The point is to inject current structure, not just a bag of words.

---

## 7. Continual-Memory Evaluation

Introduce a deterministic evaluation harness inspired by continual-learning evaluation, but adapted to an Obsidian memory system.

### 7.1 Evaluation questions

The harness should measure at least:

- recall: can the system retrieve the right topic/concept after ingest?
- retention: does relevant memory remain retrievable after time passes?
- interference: does new knowledge crowd out older, still-relevant knowledge?
- convergence: does repeated linking to a topic make retrieval more topic-centric over time?

### 7.2 Test fixture shape

Tests should build a temporary vault with:

- several topics
- several literature notes per topic
- some orphan notes
- controlled timestamps
- controlled activation history

This allows deterministic replay of memory evolution.

### 7.3 Minimum test scenarios

#### Scenario A: same-session recall

- write a new concept or literature note
- activate it twice in one session
- verify it appears in session memory immediately
- verify it enters long-term activation memory after flush

#### Scenario B: decay discrimination

- seed one high-frequency entry and one low-frequency entry
- advance timestamps
- run decay
- verify the high-frequency entry survives longer or ranks higher

#### Scenario C: topic convergence

- create a literature note under an existing topic
- update activation memory
- verify future formatting/query ranking favors the topic over the raw note

#### Scenario D: interference control

- seed two unrelated topics with stable activation
- heavily activate one new topic
- verify the second topic is not dropped prematurely if still above retention threshold

#### Scenario E: session rejection carry

- reject a topic suggestion during the session
- verify the rejected target is down-ranked immediately in that same session
- verify explicit feedback still persists through `_events.jsonl`

### 7.4 Output metrics

This does not need a large benchmark framework. Simple deterministic assertions are enough, but the harness should also support summary metrics such as:

- recall@k for topic retrieval
- number of surviving entries after decay
- top-1 topic stability across repeated updates

### 7.5 Product-facing evaluation metrics

Beyond deterministic unit-style checks, the system should also expose a few product-facing quality metrics.

Recommended metrics:

- topic recall@k for `query`
- session-hit rate for `query` and `organize`
- orphan count before and after `organize`
- topic convergence rate:
  how often repeated related notes end up grouped under one stable topic instead of remaining fragmented
- suggestion regret proxy:
  how often a target suggested in one session is explicitly rejected in the same or next session

These metrics do not require telemetry infrastructure in v1. They can be measured with deterministic fixtures and summary assertions in tests first.

---

## 8. Organize Quality Heuristics

`organize` should not be a simple "number of matches => topic, one match => moc" rule forever.

The next quality step is to make organize recommendations depend on structure, not just count.

### 8.1 Desired signals

The `organize` path should consider:

- whether an existing topic already matches strongly
- whether the matched notes are mostly orphans
- whether session memory shows the topic is actively being worked on
- whether matched notes are mostly source notes or already-synthesized topics
- whether notes share the same parent topic or are fragmented across multiple weak parents

### 8.2 Suggested organize scoring

Practical scoring signals:

- existing topic match: strong positive toward `topic`
- multiple orphan notes on one subject: positive toward `topic`
- one shallow cluster with mostly links and little synthesis: positive toward `moc`
- session-active topic with strong lexical overlap: prefer updating or converging into that topic
- widespread fragmentation across many weakly-related notes: lower confidence, surface a topic suggestion instead of a strong recommendation

### 8.3 Organize outputs

The organize helper should eventually return richer signals than just `topic|moc`:

```json
{
  "suggested_output": "topic",
  "confidence": "high",
  "reasons": [
    "3 orphan literature notes share the same subject",
    "active session topic overlaps strongly",
    "existing topic candidate is weak"
  ]
}
```

This keeps the system explainable and debuggable.

---

## 9. Implementation Outline

Recommended order:

| Step | Scope | Main files |
|---|---|---|
| 1 | add session-memory module and tests | `skills/obsidian/session_memory.py`, `tests/test_session_memory.py` |
| 2 | integrate session memory into writer/query support paths | `skills/obsidian/obsidian_writer.py`, `skills/obsidian/SKILL.md` |
| 3 | extend activation memory with `topic_links` and topic-first formatting | `skills/obsidian/memory_manager.py`, tests |
| 4 | wire source-to-topic consolidation updates | `obsidian_writer.py`, tests |
| 5 | add continual-memory evaluation tests | `tests/test_memory_manager.py`, `tests/test_obsidian_writer.py` |

The first user-visible win should come from step 2, not from metric work alone.

---

## 10. Next Stage

After the initial layered-memory rollout is stable, the recommended next-stage work is:

1. improve `organize` quality using the heuristics in §8
2. add product-facing evaluation metrics from §7.5

That sequence matters. Better organize behavior reduces fragmentation; the metrics then tell us whether it really worked.

---

## 11. Non-Goals

- importing `nested_learning` runtime code or adding Torch dependencies
- implementing CMS neural mechanisms directly inside `claude-obsidian`
- replacing lexical retrieval with embeddings in this iteration
- auto-generating topic content without explicit user confirmation/update flows

The value taken from `nested_learning` is the memory layering model and the evaluation mindset, not the training stack.

---

## 12. Acceptance Criteria

- the system tracks current-session focus explicitly, not only long-term activations
- query and organize flows can use session memory before vault-wide fallback
- `_memory.jsonl` can point users toward parent topics, not only raw notes
- repeated source-note updates make topic retrieval more stable
- tests cover recall, decay, interference, and topic convergence
