# Topic-First Retrieval Design

**Date:** 2026-04-14
**Status:** Draft
**Scope:** Fight knowledge fragmentation and catastrophic forgetting by making `topic` notes the primary retrieval surface

---

## 1. Problem

The vault grows by accretion: fleeting notes, captures, conversation logs. Without a forcing function, notes accumulate as isolated fragments. Two failure modes emerge:

- **Fragmentation on read**: `query` mode currently Greps across the full knowledge base and returns hits from many fragments. Users get overlapping, contradictory pieces instead of a single synthesized answer.
- **Catastrophic forgetting on write**: A literature note captured in month 1 has no structural hook into the vault once the user stops thinking about it. It does not surface on retrieval unless searched by exact keyword.

The right primitive already exists: `topic` notes have `主题说明`, `当前结论`, `重要资料`, `未解决问题`. What is missing is **read-path preference** and **write-path fallback**.

---

## 2. Goal

Make `topic` notes the default retrieval surface. Literature and fleeting notes become the drill-down layer, not the primary answer source.

Concretely:

- `query` returns topic summaries first; details on demand
- every literature/log capture either joins an existing topic or surfaces a "create topic" suggestion; orphans are detected and reported, not silently tolerated
- topic notes whose synthesis has fallen behind their linked literature are flagged as stale

This design does **not** add:

- embedding-based retrieval (may come in v2 if lexical proves insufficient)
- auto-created topic notes without user confirmation
- automatic rewriting of topic synthesis from literature content

---

## 3. Read Path: Two-Tier Query

`query` mode is restructured into two tiers.

### Tier 1: Topic summaries

Scan only `topic` note files. For each match, read only:

- `主题说明`
- `当前结论`
- `未解决问题`

Compose the answer from these fields, with per-claim citations pointing to the source topic note.

If Tier 1 yields no hit, fall through to Tier 2.

### Tier 2: Drill-down on request

Surface literature and project hits as secondary results, grouped under the topic they belong to (via backlink or `重要资料` field). Present as:

```
Topic: <topic name> — <one-line 当前结论>
  [detail] [[Literature - ...]] — <matched excerpt>
  [detail] [[Literature - ...]] — <matched excerpt>
```

Drill-down content is loaded only when the user asks "展开" / "细节" / "给我原文".

### Orphan handling

Literature and project notes that match the query but have no topic parent are reported under a separate section:

```
Unlinked fragments (consider organizing into a topic):
  [[Literature - ...]]
```

This makes fragmentation visible on every query rather than deferring it to a manual `lint` run.

---

## 4. Write Path: Topic Fallback

Current `capture` and `log` flows already call `suggest_links()` and prefer `topic` matches. Two changes:

### 4.1 Hard prompt when no strong topic match

If link suggestions return no `topic` candidate above a confidence threshold, the skill must surface `[Topic suggestion]` as a **default prompt**, not an optional hint.

The user sees:

```
No topic matched "<capture title>". Options:
  [1] Create new topic: <proposed topic name>
  [2] Attach to existing topic: <low-confidence candidate>
  [3] Leave unlinked (will surface in next lint as orphan)
```

Leaving unlinked is still allowed (option 3), but the user actively chose it and the note is tracked as an orphan.

### 4.2 Orphan tracking

Literature and project notes created without a topic parent are recorded as a correction event:

```json
{"ts": "...", "note": "Literature - ...", "issue_type": "orphan-on-create", "detected_by": "capture", "resolved": false}
```

This reuses the existing `_corrections.jsonl` stream from the observability design. When the user later attaches a topic, the event is resolved.

---

## 5. Forgetting Detection: Stale Synthesis

Add a new lint check: `stale-synthesis`.

Trigger condition:

- note is a `topic`
- there exist linked literature notes whose `updated` timestamp is more than 30 days newer than the topic's `updated` timestamp

Output:

```
stale-synthesis: [[Topic - ...]]
  last synthesized: 2026-02-14
  linked literature updated since:
    - [[Literature - ...]] (2026-03-22)
    - [[Literature - ...]] (2026-04-08)
```

Correction event emitted with `issue_type: "stale-synthesis"`.

This does not auto-update the topic. The user decides whether to run `cascade-update` or accept that the topic is a historical snapshot.

---

## 6. Topic Scout (Periodic)

Capture is a fast path. Users often record something without knowing its home. The topic-fallback prompt in §4.1 handles the immediate case, but users will still choose option 3 sometimes, and pre-existing orphans exist from before this design.

Add a new mode: `topic-scout`.

Behavior:

- scan `00-Inbox/` and `03-Knowledge/` for notes without a topic parent
- lexically cluster by shared vocabulary and existing tags
- propose topic candidates to the user:

```
Cluster A (5 notes, suggested topic: "LLM inference optimization"):
  [[Literature - KV Cache]]
  [[Literature - Speculative Decoding]]
  ...
Cluster B (3 notes, suggested topic: "Obsidian plugin patterns"):
  ...
```

User picks clusters to materialize as topics. The skill creates the topic note with `重要资料` populated from the cluster.

Runs on demand, not automatically.

---

## 7. Execution Order

Recommended implementation sequence by ROI:

| Step | Scope | Files |
|---|---|---|
| 1 | Two-tier query (§3) | `SKILL.md` query section only; no Python changes |
| 2 | Topic fallback prompt (§4.1) | `SKILL.md` capture/log/write sections |
| 3 | Orphan-on-create event (§4.2) | `obsidian_writer.py` capture/write path |
| 4 | stale-synthesis lint check (§5) | `obsidian_writer.py` `lint_vault()` |
| 5 | `topic-scout` mode (§6) | new mode in `obsidian_writer.py` + `SKILL.md` |

Step 1 alone should deliver a visible improvement in query quality. Later steps depend on it — if topic-first retrieval does not feel better, the rest of this design is unjustified.

---

## 8. Open Questions

- **Topic confidence threshold** (§4.1): what score counts as "strong match"? Needs calibration against existing `suggest_links()` output on the current vault.
- **Clustering method** (§6): pure lexical (tf-idf over note titles + tags) vs. optional embedding. Start lexical; revisit if clusters are noisy.
- **Tier 1 fallback granularity** (§3): if Tier 1 hits multiple topics, should the answer cite all of them or pick the highest-scoring one? Probably all, with relative weighting.
- **Interaction with cascade-update** (§5): stale-synthesis detection surfaces the need for `cascade-update`, but `cascade-update` needs the user to point at a source literature note. Should stale-synthesis output suggest a specific driver literature note, or leave that to the user?

---

## 9. Non-Goals

- Embedding or vector retrieval. Lexical + topic structure first; vectors only if proven insufficient.
- Auto-generating topic notes without user confirmation.
- Rewriting topic synthesis from literature without explicit `cascade-update` flow.
- Changing the note type schema.
