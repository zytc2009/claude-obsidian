# Note Model And Link Suggestion Design

**Date:** 2026-04-10
**Status:** Approved
**Scope:** Information architecture, note templates, and link suggestion direction

---

## 1. Goal

This project is a personal knowledge organization assistant for Obsidian.

It should help the user:

- quickly capture fleeting thoughts
- store useful external materials into the vault
- record work problems and solution processes
- turn fragmented notes into structured topic summaries

The primary value is not generic note writing. The primary value is helping fragmented inputs converge into reusable knowledge.

---

## 2. Core Note Model

The system should center on four note types:

### `fleeting`

Purpose:

- quick capture
- short thoughts
- ideas from AI conversations
- points worth verifying later

Characteristics:

- lowest friction
- appended to daily notes
- does not require full structure

### `literature`

Purpose:

- store external materials
- archive articles, papers, blog posts, docs, posts, and other references
- support AI learning as part of material organization

Characteristics:

- represents external input
- should preserve source and key ideas
- can later feed into `topic`

### `project`

Purpose:

- record concrete work problems, investigation, and solutions
- used for engineering issues, implementation notes, and practical problem solving

Characteristics:

- keep the existing `project` name because it matches user habit
- semantically narrower than traditional project management
- focuses on problem solving rather than planning

### `topic`

Purpose:

- synthesize existing knowledge into a structured understanding page
- organize conclusions across `literature` and `project`
- serve as the main page for systematic整理 and future writing

Characteristics:

- represents synthesis rather than raw input
- should reflect the user's current understanding
- should be a natural source for future blog drafts

---

## 3. Role Boundaries

Each type should have a clear role:

- `fleeting`: temporary thoughts and low-cost capture
- `literature`: external input
- `project`: practical problem and solution records
- `topic`: synthesized understanding

Typical flows:

- external material -> `literature`
- work issue -> `project`
- fragmented thought -> `fleeting`
- literature/project accumulation -> `topic`

`topic` is the integration layer. It should not behave like a raw source note.

---

## 4. Project Template

`project` should use a lightweight problem-solving template.

Required structure:

- 项目描述
- 原因分析
- 排查过程
- 解决方案
- 结果验证
- 风险与遗留问题

Design decisions:

- merge goal and symptom into `项目描述`
- remove heavy project-management fields such as completion criteria and task breakdown
- keep the template focused on reusable engineering knowledge

Draft routing for `project` should be based on this six-field structure.

---

## 5. Topic Template

`topic` should be a synthesis page rather than a generic summary shell.

Recommended structure:

- 主题说明
- 核心问题
- 当前结论
- 关键资料
- 相关项目
- 未解决问题

Design decisions:

- `topic` should aggregate `literature` and `project`
- it should emphasize current understanding, not source reconstruction
- it should stay close to future systematic output and blog writing

Draft routing for `topic` should be based on whether the page already has enough structure to count as a real synthesis note.

---

## 6. Link Suggestion Direction

`link suggestion` is a high-value feature and should be improved before other advanced vault-management features.

Its main value is not automatic linking. Its main value is helping the user discover where a new note belongs.

Priority of suggestions:

1. suggest relevant existing `topic` notes
2. suggest relevant existing `moc` notes
3. eventually suggest creating a new `topic` when no strong match exists

### Desired behavior

For a newly written note, the system should help answer:

- which existing topic does this belong to
- which topic is discussing a nearby problem
- which notes are worth grouping together

### First implementation direction

The first revision should:

- prioritize matching against `topic` over `moc`
- inspect both title and meaningful body sections
- keep the number of suggestions small
- favor precision over recall to avoid noise

### Explanation requirement

Suggestion output should move toward explainable recommendations, for example:

- matched keywords
- matched section or note title
- relative confidence or priority

This can be implemented incrementally. The first pass does not need full scoring sophistication.

---

## 7. Secondary Features

The following features remain useful, but are secondary to the core note workflow:

- `_index.md` as a global navigation page
- `lint` for broken links, inbox backlog, and skeleton notes

These should support the main workflow, not dominate the product direction.

---

## 8. Implementation Order

Changes should be executed in this order:

1. update templates and required-field logic in `obsidian_writer.py`
2. update tests to reflect the new note model
3. update `SKILL.md` and `README.md`
4. improve `link suggestion` with topic-first matching
5. run full pytest verification

