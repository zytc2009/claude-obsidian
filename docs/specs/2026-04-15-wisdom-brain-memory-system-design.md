# Wisdom Brain — Active Memory System Design

**Date:** 2026-04-15  
**Status:** Approved  
**Scope:** Extend claude-obsidian with a two-layer active memory system (智慧大脑), merging the learning system and memory system into one unified brain.

---

## 1. Background

The current system forms a working loop:

```
学习系统 (claude-obsidian) → 记忆系统 (Obsidian vault)
决策系统 (cli-assistant)   → 执行系统 (Harness_engineering)
```

The gap: Obsidian is a **knowledge store**, not a **working memory**. An agent starting a new session has no sense of "what's been on my mind lately." It must either search from scratch or rely on the user to provide context manually.

The goal: add an active memory layer between the agent and Obsidian — one that maintains recently active concepts, decays unused ones, and automatically enriches the agent's context on every interaction. Inspired by the CMS (Continuous Memory System) model and the Hope architecture (Self-Referential Titans + CMS).

---

## 2. Design Goals

- Agent automatically "remembers" recently used concepts without explicit queries
- Memory decays naturally over real time (low-frequency knowledge fades)
- Memory is reinforced when concepts appear in conversation or new notes
- Obsidian remains the authoritative knowledge store; memory is a hot cache
- No ML dependencies in v1 — keyword-based matching throughout
- Single codebase: everything lives inside claude-obsidian

---

## 3. Architecture

```
claude-obsidian/
  skills/obsidian/
    memory_manager.py     ← NEW: manages the active word library
    obsidian_writer.py    ← EXTENDED: triggers memory update on note write
    SKILL.md              ← EXTENDED: auto-injects memory context each call

Obsidian Vault/
  _memory.jsonl           ← NEW: persistent long-term active word library
  _events.jsonl           ← existing
  _corrections.jsonl      ← existing
```

### Two-Layer Memory

| Layer | Storage | Lifetime | Purpose |
|-------|---------|----------|---------|
| Short-term activation | In-memory Python dict | Current session | Words activated in this conversation |
| Long-term active library | `_memory.jsonl` | Cross-session, real-time decay | Persistent active concepts |

---

## 4. Data Model

Each entry in `_memory.jsonl`:

```json
{
  "word": "Titans",
  "aliases": ["自参考学习", "test-time"],
  "activation_score": 0.85,
  "frequency": 12,
  "last_activated": "2026-04-15T10:30:00",
  "created": "2026-04-10T09:00:00",
  "decay_rate": 0.05,
  "obsidian_links": ["Literature - Titans论文.md", "Topic - Harness Engineering.md"]
}
```

**Field notes:**
- `decay_rate` is per-item: high-frequency words get lower decay rates (harder to forget)
- `obsidian_links` enables drill-down: activating a word can expand to full Obsidian notes
- `aliases` enable associative matching ("自参考学习" → activates "Titans")

---

## 5. Activation and Forgetting

### Activation Formula (CMS-inspired)

```
activation(t) = base_score × e^(-decay_rate × days_since_last_access)
              + log(frequency + 1) × 0.1
```

- `base_score`: score at last access (starts at 1.0)
- `decay_rate`: auto-adjusts — high-frequency words: ~0.02 (slow), low-frequency: ~0.15 (fast)
- `frequency bonus`: floor that prevents frequent words from fully disappearing

### Decay Scenarios

| Scenario | Result |
|----------|--------|
| Just reinforced today | score ≈ 0.9–1.0, appears in injected context |
| Learned 7 days ago, not revisited | score ≈ 0.4–0.6, still in library |
| 30 days no access, low frequency | score < 0.1, **auto-pruned** |
| Old word reappears | score +0.3 immediately, decay_rate × 0.9 (harder to forget) |

### Session-End Consolidation ("Sleep Effect")

```
Short-term layer (words activated this session)
  ↓
  ① Already in long-term library → activation++, decay_rate slightly reduced
  ② Not in library, activated ≥ 2× this session → promoted to long-term library
  ③ Activated only once → discarded (noise filter)
```

Words must appear at least twice in a session to enter long-term memory — mimicking how humans consolidate only repeated impressions.

### Capacity

Long-term library cap: **500 items** (configurable). When exceeded, prune the lowest `activation_score` entries.

---

## 6. Context Injection

### Trigger Flow

```
User message arrives
  ↓
SKILL.md extracts keywords (nouns, proper nouns, #tags, [[wikilinks]])
  ↓
memory_manager.query(keywords)
  ├─ Exact match on word / aliases
  ├─ Substring match ("自参考" → "Titans")
  └─ Shared obsidian_link association
  ↓
Return top-5 by activation_score
  ↓
Inject <active_memory> block into context
  ↓
If user says "展开" / "细节" / "给我原文"
  └─ Load full Obsidian note via existing query capability
```

### Injected Format

```
<active_memory>
● Titans (0.85)  aliases: 自参考学习, test-time
  → [[Literature - Titans论文.md]]
● CMS (0.72)  aliases: 多频率层, 连续记忆系统
● 遗忘缓解 (0.51)  aliases: catastrophic forgetting
</active_memory>
```

### Keyword Extraction (v1, no ML)

- Strip stopwords (的/是/了/in/the/a…)
- Keep: capitalized English terms, Chinese noun phrases (2–4 chars), `#tags`, `[[wikilinks]]`
- Match against `word` + `aliases` fields in memory

---

## 7. Memory Write Sources

### Source A: Obsidian Note Writes

When `obsidian_writer.py` writes a note, it calls `memory_manager.extract_and_upsert()`:

```
Write Literature / Concept / Topic note
  ↓
Extract from key fields:
  - Concept note   → word = title, aliases from "一句话定义"
  - Literature note → noun phrases from "核心观点"
  - Topic note     → phrases from "当前结论"
  ↓
Upsert to _memory.jsonl:
  - Existing word → frequency++, update obsidian_links
  - New word → create entry, initial activation_score = 0.6, decay_rate = 0.1
```

### Source B: Conversation Reinforcement

```
User message matches a word in memory
  ↓
memory_manager.activate(word)
  - activation_score += 0.3 (cap 1.0)
  - decay_rate × 0.9 (harder to forget)
  - last_activated = now
  ↓
Lazy write: batch flush to _memory.jsonl at session end
           (triggered by Claude Code Stop hook → calls memory_manager.consolidate_and_flush())
```

### Source Roles

| Source | What it produces | Typical words |
|--------|-----------------|---------------|
| Obsidian writes | Knowledge skeleton (cold start) | Titans, 梯度下降, RAG |
| Conversation activation | Recently live concepts (hot update) | Hope架构, 智慧大脑, CMS |

Obsidian builds the skeleton; conversation determines which bones are currently active.

---

## 8. Complete Data Flow

```
[Conversation] ──activate──→ [Short-term layer] ──consolidate──→ [_memory.jsonl]
                                                                       ↑        ↓
[Obsidian write] ──extract──────────────────────────────────────────────        ↓
                                                                      auto-inject↓
[Agent Context]  ←──────────────── <active_memory> ←──────────────────────────
                                          ↑
                                  on "展开" request
                               fetch full Obsidian note
```

---

## 9. New Commands

| Command | Action |
|---------|--------|
| `/obsidian memory` | Show top-20 active words with scores |
| `/obsidian memory reinforce <word>` | Manually boost activation |
| `/obsidian memory forget <word>` | Manually remove |
| `/obsidian memory decay` | Run one decay cycle immediately |

---

## 10. Out of Scope (v1)

- Semantic similarity / embeddings (keyword matching only in v1)
- Automatic cross-session conversation logging to Obsidian
- Memory sharing across multiple vaults
- Background decay daemon (decay runs lazily on access)

---

## 11. Implementation Modules

| Module | Responsibility |
|--------|---------------|
| `memory_manager.py` | Load/save `_memory.jsonl`, query, activate, decay, consolidate, prune |
| `obsidian_writer.py` (extended) | Call `extract_and_upsert()` after every note write |
| `SKILL.md` (extended) | Extract keywords from input, inject `<active_memory>`, handle `/obsidian memory` commands |

---

## 12. Success Criteria

- [ ] Agent context automatically includes top-5 relevant active words on every interaction
- [ ] Words decay and disappear after 30+ days without access (for low-frequency words)
- [ ] Writing a Concept note seeds the memory library within the same session
- [ ] A word activated twice in one session is promoted to long-term library
- [ ] `/obsidian memory` shows a readable ranked list of current active concepts
