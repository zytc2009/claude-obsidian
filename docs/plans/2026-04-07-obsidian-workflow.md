# Claude Code → Obsidian Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code skill (`/obsidian`) and a Python helper script that write structured notes directly into a local Obsidian vault from within any Claude Code session.

**Architecture:** The skill handles language understanding and content extraction, outputting a structured JSON payload. The Python script (`obsidian_writer.py`) handles all file operations — template rendering, routing, naming, and writing — with no LLM involvement. The two components communicate via CLI arguments.

**Tech Stack:** Python 3.10+ (stdlib only: `argparse`, `json`, `pathlib`, `datetime`, `os`), pytest, Claude Code skill (Markdown)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `scripts/obsidian_writer.py` | Create | CLI entry point, template renderers, routing, file writing |
| `tests/test_obsidian_writer.py` | Create | All unit + integration tests for the script |
| `tests/__init__.py` | Create | Makes tests a package |
| `pyproject.toml` | Create | pytest config |
| `skills/obsidian` | Create | Claude Code skill — intent recognition + script invocation |
| `install.sh` | Create | Copies script and skill to `~/.claude/` |

**Install targets:**
```
scripts/obsidian_writer.py  →  ~/.claude/scripts/obsidian_writer.py
skills/obsidian             →  ~/.claude/skills/obsidian
```

---

## Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

- [ ] **Step 2: Create `tests/__init__.py`**

```python
```
(empty file)

- [ ] **Step 3: Verify pytest discovers tests**

Run: `pytest --collect-only`
Expected output includes: `no tests ran` with 0 errors (no import failures)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml tests/__init__.py
git commit -m "chore: add project setup and pytest config"
```

---

## Task 2: Note Config + Routing Utilities

**Files:**
- Create: `scripts/obsidian_writer.py` (initial skeleton + routing functions)
- Create: `tests/test_obsidian_writer.py` (routing tests)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_obsidian_writer.py`:

```python
import tempfile
from datetime import date
from pathlib import Path

import pytest

from scripts.obsidian_writer import (
    NOTE_CONFIG,
    get_target_path,
    is_draft_by_content,
    make_filename,
)


class TestIsDraftByContent:
    def test_returns_true_when_all_required_empty(self):
        fields = {"核心观点": "", "方法要点": ""}
        assert is_draft_by_content("literature", fields) is True

    def test_returns_true_when_majority_empty(self):
        # literature has 2 required fields; 1 empty = 50% → not majority
        # experiment has 4 required fields; 3 empty = 75% → majority
        fields = {"实验目标": "goal", "实验环境": "", "执行步骤": "", "结论": ""}
        assert is_draft_by_content("experiment", fields) is True

    def test_returns_false_when_majority_filled(self):
        fields = {"核心观点": "content", "方法要点": "detail"}
        assert is_draft_by_content("literature", fields) is False

    def test_returns_false_when_exactly_half_empty(self):
        # 2 required, 1 empty → 50% empty → NOT majority (needs > 50%)
        fields = {"核心观点": "content", "方法要点": ""}
        assert is_draft_by_content("literature", fields) is False


class TestGetTargetPath:
    def test_returns_inbox_when_draft(self):
        vault = Path("/vault")
        result = get_target_path(vault, "literature", is_draft=True)
        assert result == Path("/vault/00-Inbox")

    def test_returns_literature_target_when_not_draft(self):
        vault = Path("/vault")
        result = get_target_path(vault, "literature", is_draft=False)
        assert result == Path("/vault/03-Knowledge/Literature")

    def test_returns_experiment_target(self):
        vault = Path("/vault")
        result = get_target_path(vault, "experiment", is_draft=False)
        assert result == Path("/vault/03-Knowledge/Experiments")

    def test_returns_topic_target(self):
        vault = Path("/vault")
        result = get_target_path(vault, "topic", is_draft=False)
        assert result == Path("/vault/03-Knowledge/Topics")

    def test_returns_project_target(self):
        vault = Path("/vault")
        result = get_target_path(vault, "project", is_draft=False)
        assert result == Path("/vault/02-Projects")


class TestMakeFilename:
    def test_returns_simple_name_when_no_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            result = make_filename("Literature", "Test Note", target)
            assert result == "Literature - Test Note.md"

    def test_appends_date_suffix_on_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "Literature - Test Note.md").touch()
            today = date.today().strftime("%Y-%m-%d")
            result = make_filename("Literature", "Test Note", target)
            assert result == f"Literature - Test Note {today}.md"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_obsidian_writer.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` (script doesn't exist yet)

- [ ] **Step 3: Create `scripts/__init__.py`** (empty, makes `scripts` importable as package)

```python
```

- [ ] **Step 4: Create `scripts/obsidian_writer.py` with routing functions**

```python
"""
obsidian_writer.py — Write structured notes to an Obsidian vault.

Usage:
  python obsidian_writer.py --type literature --title "Title" \
    --fields '{"核心观点": "..."}' --draft false

  python obsidian_writer.py --type experiment --title "RAG Baseline" \
    --fields '{}' --draft true --dry-run
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VAULT_PATH = Path(os.environ.get("OBSIDIAN_VAULT_PATH", "~/obsidian")).expanduser()

NOTE_CONFIG = {
    "literature": {
        "prefix": "Literature",
        "target": "03-Knowledge/Literature",
        "required": ["核心观点", "方法要点"],
    },
    "experiment": {
        "prefix": "Experiment",
        "target": "03-Knowledge/Experiments",
        "required": ["实验目标", "实验环境", "执行步骤", "结论"],
    },
    "topic": {
        "prefix": "Topic",
        "target": "03-Knowledge/Topics",
        "required": ["主题说明", "核心概念"],
    },
    "project": {
        "prefix": "Project",
        "target": "02-Projects",
        "required": ["项目目标", "完成标准", "任务拆分"],
    },
}

# ---------------------------------------------------------------------------
# Routing utilities
# ---------------------------------------------------------------------------

def is_draft_by_content(note_type: str, fields: dict) -> bool:
    """Return True if more than half of required fields are empty."""
    required = NOTE_CONFIG[note_type]["required"]
    empty_count = sum(1 for f in required if not fields.get(f, "").strip())
    return empty_count > len(required) / 2


def get_target_path(vault: Path, note_type: str, is_draft: bool) -> Path:
    """Return the directory path where the note should be written."""
    if is_draft:
        return vault / "00-Inbox"
    return vault / NOTE_CONFIG[note_type]["target"]


def make_filename(prefix: str, title: str, target_dir: Path) -> str:
    """Return a filename, appending today's date if a collision exists."""
    base = f"{prefix} - {title}.md"
    if not (target_dir / base).exists():
        return base
    today = date.today().strftime("%Y-%m-%d")
    return f"{prefix} - {title} {today}.md"
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
pytest tests/test_obsidian_writer.py -v
```

Expected: all 12 tests PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/obsidian_writer.py tests/test_obsidian_writer.py
git commit -m "feat: add note config and routing utilities with tests"
```

---

## Task 3: Literature Template Renderer

**Files:**
- Modify: `scripts/obsidian_writer.py` (add `render_literature`)
- Modify: `tests/test_obsidian_writer.py` (add literature tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_obsidian_writer.py`:

```python
from scripts.obsidian_writer import render_literature


class TestRenderLiterature:
    def test_includes_title_in_output(self):
        result = render_literature("Attention Is All You Need", {})
        assert "Attention Is All You Need" in result

    def test_fills_provided_field(self):
        fields = {"核心观点": "transformer architecture"}
        result = render_literature("Test", fields)
        assert "transformer architecture" in result

    def test_fills_placeholder_for_empty_field(self):
        result = render_literature("Test", {})
        assert "_待补充_" in result

    def test_frontmatter_type_is_literature(self):
        result = render_literature("Test", {})
        assert "type: literature" in result

    def test_frontmatter_includes_today_date(self):
        result = render_literature("Test", {})
        today = date.today().strftime("%Y-%m-%d")
        assert f"created: {today}" in result

    def test_source_appears_in_frontmatter_and_body(self):
        fields = {"source": "https://arxiv.org/abs/1706.03762"}
        result = render_literature("Test", fields)
        assert "https://arxiv.org/abs/1706.03762" in result
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_obsidian_writer.py::TestRenderLiterature -v
```

Expected: `ImportError: cannot import name 'render_literature'`

- [ ] **Step 3: Implement `render_literature` in `scripts/obsidian_writer.py`**

Add after the routing utilities section:

```python
# ---------------------------------------------------------------------------
# Template renderers
# ---------------------------------------------------------------------------

def _f(fields: dict, key: str) -> str:
    """Return field value or placeholder if empty."""
    return fields.get(key, "").strip() or "_待补充_"


def _frontmatter(note_type: str, fields: dict) -> str:
    today = date.today().strftime("%Y-%m-%d")
    source = fields.get("source", "").strip()
    author = fields.get("author", "").strip()
    return (
        f"---\n"
        f"type: {note_type}\n"
        f"status: draft\n"
        f"topic: []\n"
        f"tags: []\n"
        f"source: {source}\n"
        f"author: {author}\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"reviewed: false\n"
        f"---"
    )


def render_literature(title: str, fields: dict) -> str:
    fm = _frontmatter("literature", fields)
    return f"""{fm}

# 资料信息
- 标题：{title}
- 作者：{_f(fields, "author")}
- 类型：{_f(fields, "类型")}
- 链接：{_f(fields, "source")}

# 这份资料试图解决什么问题
{_f(fields, "解决的问题")}

# 核心观点
{_f(fields, "核心观点")}

# 方法要点
{_f(fields, "方法要点")}

# 值得记住的细节
{_f(fields, "细节")}

# 我不认同或存疑的地方
{_f(fields, "存疑之处")}

# 可转化为哪些概念卡
{_f(fields, "可转化概念")}

# 可做哪些验证实验
{_f(fields, "验证实验")}

# 与已有知识的连接
{_f(fields, "知识连接")}
"""
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_obsidian_writer.py::TestRenderLiterature -v
```

Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/obsidian_writer.py tests/test_obsidian_writer.py
git commit -m "feat: add literature template renderer with tests"
```

---

## Task 4: Experiment Template Renderer

**Files:**
- Modify: `scripts/obsidian_writer.py` (add `render_experiment`)
- Modify: `tests/test_obsidian_writer.py` (add experiment tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_obsidian_writer.py`:

```python
from scripts.obsidian_writer import render_experiment


class TestRenderExperiment:
    def test_includes_title_in_output(self):
        result = render_experiment("RAG Baseline", {})
        assert "RAG Baseline" in result

    def test_fills_provided_field(self):
        fields = {"实验目标": "verify RAG recall@5"}
        result = render_experiment("Test", fields)
        assert "verify RAG recall@5" in result

    def test_fills_placeholder_for_empty_field(self):
        result = render_experiment("Test", {})
        assert "_待补充_" in result

    def test_frontmatter_type_is_experiment(self):
        result = render_experiment("Test", {})
        assert "type: experiment" in result

    def test_frontmatter_includes_today_date(self):
        result = render_experiment("Test", {})
        today = date.today().strftime("%Y-%m-%d")
        assert f"created: {today}" in result
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_obsidian_writer.py::TestRenderExperiment -v
```

Expected: `ImportError: cannot import name 'render_experiment'`

- [ ] **Step 3: Implement `render_experiment` in `scripts/obsidian_writer.py`**

Add after `render_literature`:

```python
def render_experiment(title: str, fields: dict) -> str:
    fm = _frontmatter("experiment", fields)
    return f"""{fm}

# 实验目标
{_f(fields, "实验目标")}

# 背景假设
{_f(fields, "背景假设")}

# 实验环境
- 模型：{_f(fields, "模型")}
- 数据：{_f(fields, "数据")}
- 框架：{_f(fields, "框架")}
- 硬件：{_f(fields, "硬件")}
- 版本：{_f(fields, "版本")}

# 实验设计
- 自变量：{_f(fields, "自变量")}
- 对照项：{_f(fields, "对照项")}
- 指标：{_f(fields, "指标")}

# 执行步骤
{_f(fields, "执行步骤")}

# 结果记录
{_f(fields, "结果记录")}

# 结果分析
{_f(fields, "结果分析")}

# 结论
{_f(fields, "结论")}

# 下次改进
{_f(fields, "下次改进")}
"""
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_obsidian_writer.py::TestRenderExperiment -v
```

Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/obsidian_writer.py tests/test_obsidian_writer.py
git commit -m "feat: add experiment template renderer with tests"
```

---

## Task 5: Topic Template Renderer

**Files:**
- Modify: `scripts/obsidian_writer.py` (add `render_topic`)
- Modify: `tests/test_obsidian_writer.py` (add topic tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_obsidian_writer.py`:

```python
from scripts.obsidian_writer import render_topic


class TestRenderTopic:
    def test_includes_title_in_output(self):
        result = render_topic("RAG", {})
        assert "RAG" in result

    def test_fills_provided_field(self):
        fields = {"主题说明": "Retrieval Augmented Generation overview"}
        result = render_topic("RAG", fields)
        assert "Retrieval Augmented Generation overview" in result

    def test_fills_placeholder_for_empty_field(self):
        result = render_topic("Test", {})
        assert "_待补充_" in result

    def test_frontmatter_type_is_topic(self):
        result = render_topic("Test", {})
        assert "type: topic" in result
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_obsidian_writer.py::TestRenderTopic -v
```

Expected: `ImportError: cannot import name 'render_topic'`

- [ ] **Step 3: Implement `render_topic` in `scripts/obsidian_writer.py`**

Add after `render_experiment`:

```python
def render_topic(title: str, fields: dict) -> str:
    fm = _frontmatter("topic", fields)
    return f"""{fm}

# 主题说明
{_f(fields, "主题说明")}

# 我想回答的问题
{_f(fields, "问题列表")}

# 核心概念
{_f(fields, "核心概念")}

# 重要资料
{_f(fields, "重要资料")}

# 关键实验
{_f(fields, "关键实验")}

# 当前结论
{_f(fields, "当前结论")}

# 未解决问题
{_f(fields, "未解决问题")}

# 下一步学习路线
{_f(fields, "下一步路线")}
"""
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_obsidian_writer.py::TestRenderTopic -v
```

Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/obsidian_writer.py tests/test_obsidian_writer.py
git commit -m "feat: add topic template renderer with tests"
```

---

## Task 6: Project Template Renderer

**Files:**
- Modify: `scripts/obsidian_writer.py` (add `render_project`)
- Modify: `tests/test_obsidian_writer.py` (add project tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_obsidian_writer.py`:

```python
from scripts.obsidian_writer import render_project


class TestRenderProject:
    def test_includes_title_in_output(self):
        result = render_project("本地知识库搭建", {})
        assert "本地知识库搭建" in result

    def test_fills_provided_field(self):
        fields = {"项目目标": "Build local RAG demo"}
        result = render_project("Test", fields)
        assert "Build local RAG demo" in result

    def test_fills_placeholder_for_empty_field(self):
        result = render_project("Test", {})
        assert "_待补充_" in result

    def test_frontmatter_type_is_project(self):
        result = render_project("Test", {})
        assert "type: project" in result
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_obsidian_writer.py::TestRenderProject -v
```

Expected: `ImportError: cannot import name 'render_project'`

- [ ] **Step 3: Implement `render_project` in `scripts/obsidian_writer.py`**

Add after `render_topic`:

```python
def render_project(title: str, fields: dict) -> str:
    fm = _frontmatter("project", fields)
    return f"""{fm}

# 项目目标
{_f(fields, "项目目标")}

# 完成标准
{_f(fields, "完成标准")}

# 当前状态
进行中

# 任务拆分
{_f(fields, "任务拆分")}

# 相关资料
{_f(fields, "相关资料")}

# 关键实验
{_f(fields, "关键实验")}

# 风险与阻塞
{_f(fields, "风险与阻塞")}

# 产出
{_f(fields, "产出")}
"""
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_obsidian_writer.py::TestRenderProject -v
```

Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/obsidian_writer.py tests/test_obsidian_writer.py
git commit -m "feat: add project template renderer with tests"
```

---

## Task 7: CLI Entry Point + Integration Test

**Files:**
- Modify: `scripts/obsidian_writer.py` (add `RENDERERS`, `write_note`, `main`, `parse_args`)
- Modify: `tests/test_obsidian_writer.py` (add integration tests)

- [ ] **Step 1: Write failing integration tests**

Append to `tests/test_obsidian_writer.py`:

```python
import subprocess
import sys
import tempfile
from pathlib import Path


class TestWriteNote:
    def test_writes_file_to_target_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "03-Knowledge" / "Literature").mkdir(parents=True)
            fields = {"核心观点": "test insight", "方法要点": "test method"}
            path = write_note(
                vault=vault,
                note_type="literature",
                title="Test Paper",
                fields=fields,
                is_draft=False,
            )
            assert path.exists()
            assert path.name == "Literature - Test Paper.md"
            assert "test insight" in path.read_text(encoding="utf-8")

    def test_writes_draft_to_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "00-Inbox").mkdir()
            path = write_note(
                vault=vault,
                note_type="literature",
                title="Draft Paper",
                fields={},
                is_draft=True,
            )
            assert "00-Inbox" in str(path)

    def test_creates_target_directory_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            path = write_note(
                vault=vault,
                note_type="topic",
                title="RAG",
                fields={"主题说明": "overview"},
                is_draft=False,
            )
            assert path.exists()


class TestCLI:
    def test_dry_run_prints_content_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/obsidian_writer.py",
                    "--type", "topic",
                    "--title", "RAG",
                    "--fields", '{"主题说明": "overview"}',
                    "--draft", "false",
                    "--vault", tmp,
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "RAG" in result.stdout
            assert "[DRY RUN]" in result.stdout

    def test_write_mode_outputs_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/obsidian_writer.py",
                    "--type", "topic",
                    "--title", "RAG",
                    "--fields", '{"主题说明": "overview", "核心概念": "retrieval"}',
                    "--draft", "false",
                    "--vault", tmp,
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "✓ 已写入" in result.stdout
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_obsidian_writer.py::TestWriteNote tests/test_obsidian_writer.py::TestCLI -v
```

Expected: `ImportError: cannot import name 'write_note'`

- [ ] **Step 3: Add `RENDERERS`, `write_note`, `parse_args`, and `main` to `scripts/obsidian_writer.py`**

Append to the end of `scripts/obsidian_writer.py`:

```python
# ---------------------------------------------------------------------------
# Renderer dispatch
# ---------------------------------------------------------------------------

RENDERERS = {
    "literature": render_literature,
    "experiment": render_experiment,
    "topic": render_topic,
    "project": render_project,
}

# ---------------------------------------------------------------------------
# Write note
# ---------------------------------------------------------------------------

def write_note(
    vault: Path,
    note_type: str,
    title: str,
    fields: dict,
    is_draft: bool,
) -> Path:
    """Render and write a note. Creates target directory if missing."""
    target_dir = get_target_path(vault, note_type, is_draft)
    target_dir.mkdir(parents=True, exist_ok=True)

    prefix = NOTE_CONFIG[note_type]["prefix"]
    filename = make_filename(prefix, title, target_dir)
    filepath = target_dir / filename

    content = RENDERERS[note_type](title, fields)
    filepath.write_text(content, encoding="utf-8")
    return filepath

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Write a structured note to an Obsidian vault."
    )
    parser.add_argument(
        "--type",
        required=True,
        choices=list(NOTE_CONFIG.keys()),
        help="Note type",
    )
    parser.add_argument("--title", required=True, help="Note title")
    parser.add_argument(
        "--fields",
        default="{}",
        help="JSON string of field values",
    )
    parser.add_argument(
        "--draft",
        default="false",
        choices=["true", "false"],
        help="Write to Inbox instead of target directory",
    )
    parser.add_argument(
        "--vault",
        default=str(VAULT_PATH),
        help="Path to Obsidian vault (overrides OBSIDIAN_VAULT_PATH env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print rendered content without writing to disk",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    try:
        fields = json.loads(args.fields)
    except json.JSONDecodeError as e:
        print(f"Error: --fields is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    is_draft = args.draft == "true"
    vault = Path(args.vault)
    note_type = args.type

    if args.dry_run:
        content = RENDERERS[note_type](args.title, fields)
        target_dir = get_target_path(vault, note_type, is_draft)
        prefix = NOTE_CONFIG[note_type]["prefix"]
        filename = make_filename(prefix, args.title, target_dir)
        print(f"[DRY RUN] Would write to: {target_dir / filename}\n")
        print(content)
        return

    filepath = write_note(
        vault=vault,
        note_type=note_type,
        title=args.title,
        fields=fields,
        is_draft=is_draft,
    )

    rel_path = filepath.relative_to(vault)
    print(f"✓ 已写入：{rel_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests — verify they pass**

```bash
pytest tests/test_obsidian_writer.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Smoke test with real vault (dry-run)**

```bash
python scripts/obsidian_writer.py \
  --type literature \
  --title "Attention Is All You Need" \
  --fields '{"source": "https://arxiv.org/abs/1706.03762", "核心观点": "Transformer 完全基于注意力机制", "方法要点": "Multi-head self-attention"}' \
  --draft false \
  --dry-run
```

Expected: prints rendered markdown with today's date and filled fields

- [ ] **Step 6: Commit**

```bash
git add scripts/obsidian_writer.py tests/test_obsidian_writer.py
git commit -m "feat: add CLI entry point and integration tests"
```

---

## Task 8: Skill File

**Files:**
- Create: `skills/obsidian`

- [ ] **Step 1: Create `skills/obsidian`**

```markdown
---
description: Write a structured note to the Obsidian knowledge base. Use when the user asks to save research, experiments, topic overviews, or project plans to Obsidian. Triggered by /obsidian, or natural language like "帮我写一个关于X的资料笔记", "把这次实验记录下来", "建一个X主题页", "新建一个X项目".
---

You are writing a structured note to the user's local Obsidian vault at `~/obsidian/` by default, or `OBSIDIAN_VAULT_PATH` when configured.

## Step 1: Identify Note Type

Map the user's request to one of these types:

| User says | Type |
|-----------|------|
| 资料笔记, literature, 文章, 论文, 博客 | `literature` |
| 实验记录, experiment, 记录这次实验 | `experiment` |
| 主题页, topic, 主题 | `topic` |
| 项目页, project, 项目 | `project` |

If unclear, ask: "你想创建哪种笔记？literature（资料笔记）/ experiment（实验记录）/ topic（主题页）/ project（项目页）"

## Step 2: Extract Fields

Extract from the user's input or the current conversation context.

**literature** fields (JSON keys):
```
source, author, 类型, 解决的问题, 核心观点, 方法要点, 细节, 存疑之处, 可转化概念, 验证实验, 知识连接
```

**experiment** fields:
```
实验目标, 背景假设, 模型, 数据, 框架, 硬件, 版本, 自变量, 对照项, 指标, 执行步骤, 结果记录, 结果分析, 结论, 下次改进
```

**topic** fields:
```
主题说明, 问题列表, 核心概念, 重要资料, 关键实验, 当前结论, 未解决问题, 下一步路线
```

**project** fields:
```
项目目标, 完成标准, 任务拆分, 相关资料, 关键实验, 风险与阻塞, 产出
```

Leave fields empty if you cannot extract them — the script will insert `_待补充_`.

## Step 3: Determine Title

Extract a concise title from the user's input. For literature, use the paper/article name. For others, use the topic name.

## Step 4: Determine Draft Status

Set `--draft true` if:
- User says "draft", "草稿", or "先放 Inbox"
- You extracted fewer than half of the required fields

Required fields per type:
- literature: `核心观点`, `方法要点`
- experiment: `实验目标`, `实验环境`, `执行步骤`, `结论`
- topic: `主题说明`, `核心概念`
- project: `项目目标`, `完成标准`, `任务拆分`

## Step 5: Call the Script

Run using the Bash tool:

```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type <TYPE> \
  --title "<TITLE>" \
  --fields '<JSON_FIELDS>' \
  --draft <true|false>
```

Example:
```bash
python ~/.claude/scripts/obsidian_writer.py \
  --type literature \
  --title "Attention Is All You Need" \
  --fields '{"source": "https://arxiv.org/abs/1706.03762", "核心观点": "Transformer 完全基于注意力机制", "方法要点": "Multi-head self-attention + positional encoding"}' \
  --draft false
```

## Step 6: Report Result

Show the script's stdout to the user. If the script exits with an error, show stderr and explain what went wrong.

If draft was auto-triggered, add:
> 内容不完整，已存入 Inbox。补充以下字段后可移至正式目录：[list missing required fields]
```

- [ ] **Step 2: Commit**

```bash
git add skills/obsidian
git commit -m "feat: add obsidian Claude Code skill"
```

---

## Task 9: Installation Script

**Files:**
- Create: `install.sh`

- [ ] **Step 1: Create `install.sh`**

```bash
#!/usr/bin/env bash
# install.sh — Copy skill and script to ~/.claude/

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SCRIPTS_DIR="$CLAUDE_DIR/scripts"
SKILLS_DIR="$CLAUDE_DIR/skills"

echo "Installing claude-obsidian..."

cp scripts/obsidian_writer.py "$SCRIPTS_DIR/obsidian_writer.py"
echo "  ✓ Script  → $SCRIPTS_DIR/obsidian_writer.py"

cp skills/obsidian "$SKILLS_DIR/obsidian"
echo "  ✓ Skill   → $SKILLS_DIR/obsidian"

echo ""
echo "Done. Use /obsidian in any Claude Code session."
echo "Set OBSIDIAN_VAULT_PATH env var to override the default vault path."
```

- [ ] **Step 2: Run the install script**

```bash
chmod +x install.sh && ./install.sh
```

Expected output:
```
Installing claude-obsidian...
  ✓ Script  → /Users/<you>/.claude/scripts/obsidian_writer.py
  ✓ Skill   → /Users/<you>/.claude/skills/obsidian
Done. Use /obsidian in any Claude Code session.
```

- [ ] **Step 3: End-to-end manual test in a new Claude Code session**

Open a new Claude Code session and run:
```
/obsidian literature draft
```
Tell Claude: "这是一篇关于 RAG 的博客，作者是 Lewis 等人，主要观点是检索增强可以提升 LLM 的事实准确性。"

Expected: Claude writes a file to `<vault>/00-Inbox/Literature - *.md`, reports the path.

- [ ] **Step 4: Commit**

```bash
git add install.sh
git commit -m "feat: add install script"
```

---

## Self-Review Notes

**Spec coverage check:**
- [x] §4 斜杠命令 → covered in skill (Task 8)
- [x] §4 自然语言 → covered in skill description/trigger
- [x] §5.1 literature → Task 3
- [x] §5.2 experiment → Task 4
- [x] §5.3 topic → Task 5
- [x] §5.4 project → Task 6
- [x] §7 写入路由（draft → Inbox, complete → target） → Task 2 + Task 7
- [x] §8 frontmatter date injection → `_frontmatter()` in Task 3
- [x] §8 `_待补充_` placeholder → `_f()` helper in Task 3
- [x] §8 collision handling → `make_filename()` in Task 2
- [x] §8 auto-create directory → `write_note()` in Task 7
- [x] §9 unrecognized type → skill Step 1 fallback question
- [x] §9 auto-draft on incomplete → skill Step 4 logic
- [x] §10 dry-run → `--dry-run` flag in Task 7
- [x] §10 manual acceptance tests → Task 9 Step 3
