# Layered Memory Implementation Plan

**Date:** 2026-04-16
**Status:** Ready
**Scope:** Implement session memory, topic-linked activation memory, and continual-memory evaluation in `claude-obsidian`

---

## 1. Goal

Implement the design in [2026-04-16-layered-memory-and-continual-eval-design.md](/whb/work/claude-obsidian/docs/specs/2026-04-16-layered-memory-and-continual-eval-design.md) with the smallest sequence of changes that produces visible retrieval improvements early and preserves the repo's lightweight dependency model.

---

## 2. Delivery Sequence

### Phase 1: Session memory foundation

- [ ] Add `skills/obsidian/session_memory.py`
- [ ] Add tests for session-memory load/update/reset behavior
- [ ] Model: active topics, active notes, recent queries, rejected targets, open loops
- [ ] Keep storage optional and lightweight

Exit criteria:

- a session object can be created and updated deterministically
- same-session rejections and note expansions are queryable

### Phase 2: Integration into current flows

- [ ] Update `obsidian_writer.py` to record session events during suggestion and update flows
- [ ] Extend `SKILL.md` guidance to consult session memory before wider search
- [ ] Ensure session state updates on topic expansion, note drill-down, and suggestion rejection

Exit criteria:

- the agent has a concrete working-memory surface for the current session
- repeated work in one session stops rediscovering the same context from scratch

### Phase 3: Topic-linked activation memory

- [ ] Extend `MemoryManager` data model with optional `topic_links`
- [ ] Update extraction/upsert helpers to attach source concepts to parent topics when known
- [ ] Update formatted context to surface topics before raw notes when possible
- [ ] Add compatibility tests to ensure old `_memory.jsonl` entries still load

Exit criteria:

- active-memory output prefers synthesized topic nodes
- old memory files remain valid

### Phase 4: Continual-memory evaluation

- [ ] Add deterministic test fixtures for timestamps, activation histories, and topic/source relationships
- [ ] Add tests for same-session recall
- [ ] Add tests for decay discrimination
- [ ] Add tests for topic convergence
- [ ] Add tests for interference control

Exit criteria:

- memory behavior is validated by repeatable tests, not just inspected manually

### Phase 5: Organize-quality and product metrics

- [ ] Improve `organize` recommendation quality beyond raw match count
- [ ] Add explainable reasons and confidence to organize suggestions
- [ ] Add tests for orphan reduction before/after organize flows
- [ ] Add tests for query topic recall stability
- [ ] Add tests for topic convergence across repeated related note ingestion

Exit criteria:

- organize suggestions are structure-aware and explainable
- the repo has product-facing quality checks, not only mechanism checks

---

## 3. File Plan

| Action | File |
|---|---|
| Create | `skills/obsidian/session_memory.py` |
| Create | `tests/test_session_memory.py` |
| Modify | `skills/obsidian/memory_manager.py` |
| Modify | `skills/obsidian/obsidian_writer.py` |
| Modify | `skills/obsidian/SKILL.md` |
| Modify | `tests/test_memory_manager.py` |
| Modify | `tests/test_obsidian_writer.py` |
| Modify | `docs/specs/2026-04-16-layered-memory-and-continual-eval-design.md` |
| Modify | `docs/plans/2026-04-16-layered-memory-implementation.md` |

---

## 4. Verification

Run at minimum:

- `python -m pytest tests/test_session_memory.py -q`
- `python -m pytest tests/test_memory_manager.py -q`
- `python -m pytest tests/test_obsidian_writer.py -q`

If integration behavior spans multiple files, run the full suite:

- `python -m pytest -q`

---

## 5. Risks

- session memory can become duplicate state if it starts storing content rather than references
- topic-link inference can drift if it guesses parent topics too aggressively
- memory tests can become brittle if they depend on wall-clock time instead of controlled timestamps

Mitigations:

- store references and state, not copied note content
- attach topic links only when the relationship is explicit
- freeze timestamps in tests or seed entries directly
