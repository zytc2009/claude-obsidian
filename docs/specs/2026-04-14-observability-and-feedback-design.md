# Observability And Feedback Design

**Date:** 2026-04-14
**Status:** Approved
**Scope:** Vault-level corrections, structured suggestion feedback, log rotation, and conservative ranking bias

---

## 1. Goal

The system should become more observable and more learnable without making silent semantic changes to the vault.

This design adds:

- machine-readable correction events from lint
- machine-readable suggestion feedback events
- bounded operation-log growth
- a conservative ranking bias for future link suggestions

It does not add:

- automatic schema evolution
- hidden note rewrites
- frontmatter-level storage for suggestion event history

---

## 2. Data Flows

Two vault-level event streams are maintained:

### `corrections`

Purpose:

- record note-quality issues found by `lint`
- support later reporting, repair workflows, and trend analysis

Storage:

- `_corrections.jsonl`

Each event should include:

- `ts`
- `note`
- `issue_type`
- `detail`
- `detected_by`
- `resolved`

`corrections` is an operational quality stream, not a recommendation-learning stream.

### `suggestion_feedback`

Purpose:

- record explicit user feedback on generated suggestions
- support future ranking bias without polluting note frontmatter

Storage:

- `_events.jsonl`

Each event should include:

- `ts`
- `event_type`
- `suggestion_type`
- `source_note`
- `target_notes`
- `action`
- `reason`

Supported actions:

- `reject`
- `modify-accept`

Only explicit high-signal feedback should be stored here. Accepted suggestions that are directly reflected in note content do not need a duplicate feedback event by default.

---

## 3. Operation Log

`_log.md` remains the human-readable activity log.

Rules:

- every operation may still append a readable markdown entry
- when `_log.md` exceeds 500 entries, older entries rotate into `_log.archive.md`
- rotation should preserve order and keep the newest 500 entries in `_log.md`

The markdown log is for inspection. JSONL files are the primary machine-readable source of truth.

---

## 4. Link Suggestion Bias

`suggest_links()` may consult `_events.jsonl`, but only with a narrow scope.

Bias rules:

- only `suggestion_feedback` events of type `link` are considered
- only events for the same `source_note` are considered
- `reject` applies a stronger penalty than `modify-accept`
- the original lexical matching heuristic remains the primary ranking signal
- feedback bias may down-rank or suppress a repeated target, but it should not invent new candidates

Rationale:

- this keeps behavior predictable
- this avoids over-generalizing from one rejection to unrelated notes
- this preserves explainability in suggestion reasons

---

## 5. Feedback Capture Path

Suggestion-producing CLI flows should print a copyable feedback command hint.

This applies to:

- link suggestions
- topic suggestions
- merge candidate lists
- cascade candidate lists

The hint should:

- point to `--type suggestion-feedback`
- include `source_note`
- include `suggestion_type`
- include the surfaced target list

This keeps the event stream explicit and user-controlled while still making feedback cheap to record.

---

## 6. Non-Goals

This design intentionally does not:

- auto-upgrade schema based on free-form field drift
- store suggestion-history arrays inside note frontmatter
- make vault-wide ranking decisions from sparse feedback
- rewrite or delete historical corrections/events during normal operation

Further learning behavior should be added only after these streams prove stable and useful in daily use.
