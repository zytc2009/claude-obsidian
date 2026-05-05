# 智慧大脑活性记忆系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 在 claude-obsidian 中新增双层活性记忆系统，让 Agent 自动"记住"最近活跃的概念，并在每次对话时自动注入相关记忆上下文。

**架构：** 新增 `memory_manager.py` 模块管理 `_memory.jsonl` 持久化词库；扩展 `obsidian_writer.py` 在写笔记时自动提取词条；扩展 `SKILL.md` 自动注入记忆上下文并处理 `/obsidian memory` 命令。

**技术栈：** Python 3.9+，标准库（json/math/re/datetime/pathlib），无 ML 依赖

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| 创建 | `skills/obsidian/memory_manager.py` | 活性词库全部逻辑：增删查衰减巩固 |
| 创建 | `tests/test_memory_manager.py` | memory_manager 全部测试 |
| 修改 | `skills/obsidian/obsidian_writer.py` | 写笔记后调用 extract_and_upsert |
| 修改 | `tests/test_obsidian_writer.py` | 新增集成测试：写笔记触发记忆更新 |
| 修改 | `skills/obsidian/SKILL.md` | 新增 memory 模式 + 自动注入上下文 |

---

## Task 1：数据模型与基础增删查

**文件：**
- 创建：`skills/obsidian/memory_manager.py`
- 创建：`tests/test_memory_manager.py`

- [ ] **步骤 1：写失败测试**

新建 `tests/test_memory_manager.py`：

```python
import json
import tempfile
from pathlib import Path
import pytest
from skills.obsidian.memory_manager import MemoryManager, _MEMORY_FILE

@pytest.fixture
def vault(tmp_path):
    return tmp_path

class TestMemoryManagerLoad:
    def test_loads_empty_when_no_file(self, vault):
        mm = MemoryManager(vault)
        assert mm._long_term == {}

    def test_loads_existing_entries(self, vault):
        entry = {
            "word": "Titans", "aliases": ["test-time"],
            "activation_score": 0.8, "frequency": 5,
            "last_activated": "2026-04-15T10:00:00",
            "created": "2026-04-10T09:00:00",
            "decay_rate": 0.05, "obsidian_links": []
        }
        (vault / _MEMORY_FILE).write_text(
            json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        mm = MemoryManager(vault)
        assert "Titans" in mm._long_term
        assert mm._long_term["Titans"]["frequency"] == 5

class TestUpsert:
    def test_creates_new_entry(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("CMS", aliases=["连续记忆系统"])
        assert "CMS" in mm._long_term
        assert mm._long_term["CMS"]["frequency"] == 1
        assert "连续记忆系统" in mm._long_term["CMS"]["aliases"]

    def test_increments_frequency_on_duplicate(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("CMS")
        mm.upsert("CMS")
        assert mm._long_term["CMS"]["frequency"] == 2

    def test_merges_aliases_without_duplicates(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("CMS", aliases=["连续记忆"])
        mm.upsert("CMS", aliases=["连续记忆", "多频率层"])
        aliases = mm._long_term["CMS"]["aliases"]
        assert aliases.count("连续记忆") == 1
        assert "多频率层" in aliases

    def test_adds_obsidian_link(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("CMS", obsidian_link="Literature - CMS论文.md")
        assert "Literature - CMS论文.md" in mm._long_term["CMS"]["obsidian_links"]

    def test_does_not_duplicate_obsidian_link(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("CMS", obsidian_link="Literature - CMS论文.md")
        mm.upsert("CMS", obsidian_link="Literature - CMS论文.md")
        assert mm._long_term["CMS"]["obsidian_links"].count("Literature - CMS论文.md") == 1

class TestSave:
    def test_save_and_reload(self, vault):
        mm = MemoryManager(vault)
        mm.upsert("RAG", aliases=["检索增强"])
        mm._save()
        mm2 = MemoryManager(vault)
        assert "RAG" in mm2._long_term
        assert "检索增强" in mm2._long_term["RAG"]["aliases"]
```

- [ ] **步骤 2：运行测试确认失败**

```bash
cd <repo-root>
python -m pytest tests/test_memory_manager.py -v 2>&1 | head -30
```

预期：`ModuleNotFoundError: No module named 'skills.obsidian.memory_manager'`

- [ ] **步骤 3：实现最小代码**

创建 `skills/obsidian/memory_manager.py`：

```python
"""
memory_manager.py — 活性记忆系统

两层记忆：
  长期层：_memory.jsonl，跨会话，真实时间衰减
  短期层：内存 dict，当前会话，巩固时晋升到长期层
"""

import json
import math
import re
from datetime import datetime
from pathlib import Path

_MEMORY_FILE = "_memory.jsonl"
_MAX_MEMORY_ITEMS = 500
_MIN_ACTIVATION_THRESHOLD = 0.1
_INITIAL_ACTIVATION_SCORE = 0.6
_INITIAL_DECAY_RATE = 0.1

_STOPWORDS = set(
    "的是了在和与或但因为所以如果那么这个那个一个 "
    "a an the and or but in on at to of for with by is are was were".split()
)


def _extract_keywords(text: str) -> list:
    """从文本中提取关键词（名词、专有词，无 ML 依赖）。"""
    if not text:
        return []
    wikilinks = re.findall(r'\[\[([^\]]+)\]\]', text)
    tags = re.findall(r'#(\w+)', text)
    english = re.findall(r'\b[A-Z][a-zA-Z]{1,}\b', text)
    chinese = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
    all_words = wikilinks + tags + english + chinese
    return [w for w in all_words if w.lower() not in _STOPWORDS and len(w) >= 2]


class MemoryManager:
    def __init__(self, vault: Path):
        self.vault = vault
        self._memory_path = vault / _MEMORY_FILE
        self._long_term: dict = {}   # word -> entry dict
        self._short_term: dict = {}  # word -> activation count this session
        self._load()

    def _load(self):
        if not self._memory_path.exists():
            return
        with self._memory_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                self._long_term[entry["word"]] = entry

    def _save(self):
        self._memory_path.parent.mkdir(parents=True, exist_ok=True)
        with self._memory_path.open("w", encoding="utf-8") as f:
            for entry in self._long_term.values():
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _current_activation(self, entry: dict) -> float:
        last = datetime.fromisoformat(entry["last_activated"])
        days = (datetime.now() - last).total_seconds() / 86400
        base = entry["activation_score"] * math.exp(-entry["decay_rate"] * days)
        freq_bonus = math.log(entry["frequency"] + 1) * 0.1
        return min(1.0, base + freq_bonus)

    def upsert(self, word: str, aliases: list = None, obsidian_link: str = None):
        """新增或更新长期记忆中的词条。"""
        if word in self._long_term:
            entry = dict(self._long_term[word])
            entry["frequency"] += 1
            if aliases:
                existing = set(entry.get("aliases", []))
                entry["aliases"] = list(existing | set(aliases))
            if obsidian_link:
                links = entry.setdefault("obsidian_links", [])
                if obsidian_link not in links:
                    links.append(obsidian_link)
        else:
            now = datetime.now().isoformat(timespec="seconds")
            entry = {
                "word": word,
                "aliases": list(aliases) if aliases else [],
                "activation_score": _INITIAL_ACTIVATION_SCORE,
                "frequency": 1,
                "last_activated": now,
                "created": now,
                "decay_rate": _INITIAL_DECAY_RATE,
                "obsidian_links": [obsidian_link] if obsidian_link else [],
            }
        self._long_term[word] = entry
```

- [ ] **步骤 4：运行测试确认通过**

```bash
python -m pytest tests/test_memory_manager.py::TestMemoryManagerLoad tests/test_memory_manager.py::TestUpsert tests/test_memory_manager.py::TestSave -v
```

预期：全部 PASS

- [ ] **步骤 5：提交**

```bash
git add skills/obsidian/memory_manager.py tests/test_memory_manager.py
git commit -m "feat: add MemoryManager with load/save/upsert"
```

---

## Task 2：衰减与淘汰机制

**文件：**
- 修改：`skills/obsidian/memory_manager.py`
- 修改：`tests/test_memory_manager.py`

- [ ] **步骤 1：写失败测试**

在 `tests/test_memory_manager.py` 末尾追加：

```python
from datetime import timedelta
from unittest.mock import patch

class TestDecay:
    def _make_entry(self, vault, word, score, decay_rate, days_ago):
        mm = MemoryManager(vault)
        last = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
        mm._long_term[word] = {
            "word": word, "aliases": [], "activation_score": score,
            "frequency": 1, "last_activated": last, "created": last,
            "decay_rate": decay_rate, "obsidian_links": [],
        }
        return mm

    def test_high_score_word_survives_7_days(self, vault):
        mm = self._make_entry(vault, "Titans", 1.0, 0.05, 7)
        mm.run_decay()
        assert "Titans" in mm._long_term
        assert mm._long_term["Titans"]["activation_score"] > 0.1

    def test_low_freq_word_pruned_after_30_days(self, vault):
        mm = self._make_entry(vault, "OldWord", 1.0, 0.15, 30)
        mm.run_decay()
        assert "OldWord" not in mm._long_term

    def test_prune_keeps_top_n_by_score(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        for i in range(10):
            mm._long_term[f"word{i}"] = {
                "word": f"word{i}", "aliases": [],
                "activation_score": i * 0.1, "frequency": 1,
                "last_activated": now, "created": now,
                "decay_rate": 0.01, "obsidian_links": [],
            }
        mm.prune(max_items=5)
        assert len(mm._long_term) == 5
        # 保留分数最高的 5 个（word5~word9）
        assert "word9" in mm._long_term
        assert "word0" not in mm._long_term
```

- [ ] **步骤 2：运行测试确认失败**

```bash
python -m pytest tests/test_memory_manager.py::TestDecay -v
```

预期：`AttributeError: 'MemoryManager' object has no attribute 'run_decay'`

- [ ] **步骤 3：实现衰减逻辑**

在 `memory_manager.py` 的 `MemoryManager` 类中添加（放在 `upsert` 方法后）：

```python
    def run_decay(self):
        """更新所有词条的激活分数，淘汰低于阈值的词条。"""
        updated = {}
        for word, entry in self._long_term.items():
            score = self._current_activation(entry)
            if score >= _MIN_ACTIVATION_THRESHOLD:
                entry = dict(entry)
                entry["activation_score"] = round(score, 4)
                updated[word] = entry
        self._long_term = updated

    def prune(self, max_items: int = _MAX_MEMORY_ITEMS):
        """保留激活分数最高的 max_items 条词条。"""
        if len(self._long_term) <= max_items:
            return
        sorted_entries = sorted(
            self._long_term.values(),
            key=lambda e: self._current_activation(e),
            reverse=True,
        )
        self._long_term = {e["word"]: e for e in sorted_entries[:max_items]}
```

- [ ] **步骤 4：运行测试确认通过**

```bash
python -m pytest tests/test_memory_manager.py::TestDecay -v
```

预期：全部 PASS

- [ ] **步骤 5：提交**

```bash
git add skills/obsidian/memory_manager.py tests/test_memory_manager.py
git commit -m "feat: add decay and prune to MemoryManager"
```

---

## Task 3：查询与激活（含短期层）

**文件：**
- 修改：`skills/obsidian/memory_manager.py`
- 修改：`tests/test_memory_manager.py`

- [ ] **步骤 1：写失败测试**

在 `tests/test_memory_manager.py` 末尾追加：

```python
class TestQuery:
    def _populated_mm(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        for word, aliases, score, links in [
            ("Titans", ["自参考学习", "test-time"], 0.9, ["Literature - Titans.md"]),
            ("CMS",    ["多频率层", "连续记忆"],    0.7, []),
            ("RAG",    ["检索增强生成"],             0.5, []),
        ]:
            mm._long_term[word] = {
                "word": word, "aliases": aliases,
                "activation_score": score, "frequency": 3,
                "last_activated": now, "created": now,
                "decay_rate": 0.02, "obsidian_links": links,
            }
        return mm

    def test_exact_word_match(self, vault):
        mm = self._populated_mm(vault)
        results = mm.query(["Titans"])
        assert results[0]["word"] == "Titans"

    def test_alias_match(self, vault):
        mm = self._populated_mm(vault)
        results = mm.query(["自参考"])
        words = [r["word"] for r in results]
        assert "Titans" in words

    def test_returns_at_most_5(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        for i in range(10):
            mm._long_term[f"word{i}"] = {
                "word": f"word{i}", "aliases": [f"alias{i}"],
                "activation_score": 0.5, "frequency": 1,
                "last_activated": now, "created": now,
                "decay_rate": 0.05, "obsidian_links": [],
            }
        results = mm.query(["word"])
        assert len(results) <= 5

    def test_returns_empty_for_no_match(self, vault):
        mm = self._populated_mm(vault)
        results = mm.query(["nonexistent_xyz"])
        assert results == []

    def test_sorted_by_activation_score(self, vault):
        mm = self._populated_mm(vault)
        results = mm.query(["记忆", "Titans", "CMS"])
        scores = [mm._current_activation(r) for r in results]
        assert scores == sorted(scores, reverse=True)


class TestActivate:
    def test_boosts_activation_score(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        mm._long_term["Titans"] = {
            "word": "Titans", "aliases": [], "activation_score": 0.5,
            "frequency": 2, "last_activated": now, "created": now,
            "decay_rate": 0.1, "obsidian_links": [],
        }
        mm.activate("Titans")
        assert mm._long_term["Titans"]["activation_score"] > 0.5

    def test_activation_capped_at_1(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        mm._long_term["X"] = {
            "word": "X", "aliases": [], "activation_score": 0.95,
            "frequency": 1, "last_activated": now, "created": now,
            "decay_rate": 0.1, "obsidian_links": [],
        }
        mm.activate("X")
        assert mm._long_term["X"]["activation_score"] <= 1.0

    def test_reduces_decay_rate(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        mm._long_term["Y"] = {
            "word": "Y", "aliases": [], "activation_score": 0.5,
            "frequency": 1, "last_activated": now, "created": now,
            "decay_rate": 0.1, "obsidian_links": [],
        }
        mm.activate("Y")
        assert mm._long_term["Y"]["decay_rate"] < 0.1

    def test_increments_short_term_counter(self, vault):
        mm = MemoryManager(vault)
        mm.activate("NewWord")
        assert mm._short_term.get("NewWord", 0) == 1
        mm.activate("NewWord")
        assert mm._short_term.get("NewWord", 0) == 2
```

- [ ] **步骤 2：运行测试确认失败**

```bash
python -m pytest tests/test_memory_manager.py::TestQuery tests/test_memory_manager.py::TestActivate -v
```

预期：`AttributeError: 'MemoryManager' object has no attribute 'query'`

- [ ] **步骤 3：实现 query 和 activate**

在 `memory_manager.py` 的 `MemoryManager` 类中，`prune` 方法后添加：

```python
    def query(self, keywords: list) -> list:
        """返回最多 5 条最相关的活性词，按激活分数排序。"""
        matched = set()
        for kw in keywords:
            kw_lower = kw.lower()
            for word, entry in self._long_term.items():
                if kw_lower in word.lower():
                    matched.add(word)
                    continue
                for alias in entry.get("aliases", []):
                    if kw_lower in alias.lower():
                        matched.add(word)
                        break

        # 同 obsidian_link 的关联词
        matched_links = set()
        for word in matched:
            links = set(self._long_term[word].get("obsidian_links", []))
            for other_word, other_entry in self._long_term.items():
                if other_word not in matched:
                    other_links = set(other_entry.get("obsidian_links", []))
                    if links & other_links:
                        matched_links.add(other_word)

        all_matched = matched | matched_links
        results = [self._long_term[w] for w in all_matched]
        results.sort(key=lambda e: self._current_activation(e), reverse=True)
        return results[:5]

    def activate(self, word: str):
        """强化长期记忆中的词，并记录短期激活次数。"""
        self._short_term[word] = self._short_term.get(word, 0) + 1
        if word in self._long_term:
            entry = dict(self._long_term[word])
            entry["activation_score"] = min(1.0, round(entry["activation_score"] + 0.3, 4))
            entry["decay_rate"] = round(entry["decay_rate"] * 0.9, 4)
            entry["frequency"] += 1
            entry["last_activated"] = datetime.now().isoformat(timespec="seconds")
            self._long_term[word] = entry
```

- [ ] **步骤 4：运行测试确认通过**

```bash
python -m pytest tests/test_memory_manager.py::TestQuery tests/test_memory_manager.py::TestActivate -v
```

预期：全部 PASS

- [ ] **步骤 5：提交**

```bash
git add skills/obsidian/memory_manager.py tests/test_memory_manager.py
git commit -m "feat: add query and activate to MemoryManager"
```

---

## Task 4：会话巩固 + 上下文格式化

**文件：**
- 修改：`skills/obsidian/memory_manager.py`
- 修改：`tests/test_memory_manager.py`

- [ ] **步骤 1：写失败测试**

在 `tests/test_memory_manager.py` 末尾追加：

```python
class TestConsolidate:
    def test_promotes_word_activated_twice(self, vault):
        mm = MemoryManager(vault)
        mm._short_term["NewConcept"] = 2
        mm.consolidate_and_flush()
        assert "NewConcept" in mm._long_term

    def test_discards_word_activated_once(self, vault):
        mm = MemoryManager(vault)
        mm._short_term["Noise"] = 1
        mm.consolidate_and_flush()
        assert "Noise" not in mm._long_term

    def test_clears_short_term_after_flush(self, vault):
        mm = MemoryManager(vault)
        mm._short_term["X"] = 3
        mm.consolidate_and_flush()
        assert mm._short_term == {}

    def test_saves_to_disk_on_flush(self, vault):
        mm = MemoryManager(vault)
        mm._short_term["Persistent"] = 2
        mm.consolidate_and_flush()
        mm2 = MemoryManager(vault)
        assert "Persistent" in mm2._long_term


class TestFormatContext:
    def test_returns_empty_string_when_no_memory(self, vault):
        mm = MemoryManager(vault)
        assert mm.format_context() == ""

    def test_includes_active_memory_tags(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        mm._long_term["Titans"] = {
            "word": "Titans", "aliases": ["自参考学习"],
            "activation_score": 0.9, "frequency": 5,
            "last_activated": now, "created": now,
            "decay_rate": 0.02, "obsidian_links": ["Literature - Titans.md"],
        }
        ctx = mm.format_context()
        assert "<active_memory>" in ctx
        assert "Titans" in ctx
        assert "自参考学习" in ctx
        assert "</active_memory>" in ctx

    def test_returns_at_most_5_items(self, vault):
        mm = MemoryManager(vault)
        now = datetime.now().isoformat(timespec="seconds")
        for i in range(10):
            mm._long_term[f"word{i}"] = {
                "word": f"word{i}", "aliases": [],
                "activation_score": 0.5, "frequency": 1,
                "last_activated": now, "created": now,
                "decay_rate": 0.05, "obsidian_links": [],
            }
        ctx = mm.format_context()
        assert ctx.count("●") <= 5
```

- [ ] **步骤 2：运行测试确认失败**

```bash
python -m pytest tests/test_memory_manager.py::TestConsolidate tests/test_memory_manager.py::TestFormatContext -v
```

预期：`AttributeError: 'MemoryManager' object has no attribute 'consolidate_and_flush'`

- [ ] **步骤 3：实现巩固和格式化**

在 `memory_manager.py` 的 `activate` 方法后添加：

```python
    def consolidate_and_flush(self):
        """将短期激活词晋升到长期库，运行衰减，保存到磁盘。
        由 Claude Code Stop hook 触发。"""
        for word, count in self._short_term.items():
            if count >= 2 and word not in self._long_term:
                self.upsert(word)
        self.run_decay()
        self.prune()
        self._save()
        self._short_term.clear()

    def format_context(self) -> str:
        """格式化 top-5 活性词，用于注入 Agent 上下文。"""
        top = sorted(
            self._long_term.values(),
            key=lambda e: self._current_activation(e),
            reverse=True,
        )[:5]
        if not top:
            return ""
        lines = ["<active_memory>"]
        for entry in top:
            score = self._current_activation(entry)
            aliases_str = ", ".join(entry.get("aliases", []))
            line = f"● {entry['word']} ({score:.2f})"
            if aliases_str:
                line += f"  别名: {aliases_str}"
            links = entry.get("obsidian_links", [])
            if links:
                line += f"\n  → [[{links[0]}]]"
            lines.append(line)
        lines.append("</active_memory>")
        return "\n".join(lines)

    def show_status(self, top_n: int = 20) -> str:
        """返回人类可读的活性词库状态。"""
        entries = sorted(
            self._long_term.values(),
            key=lambda e: self._current_activation(e),
            reverse=True,
        )[:top_n]
        if not entries:
            return "[Memory] 活性词库为空"
        lines = [f"[Memory] 活性词库 top-{min(top_n, len(entries))} / {len(self._long_term)} 条\n"]
        for i, entry in enumerate(entries, 1):
            score = self._current_activation(entry)
            lines.append(
                f"  {i:2}. {entry['word']:<20} score={score:.2f}  freq={entry['frequency']}"
            )
        return "\n".join(lines)
```

- [ ] **步骤 4：运行测试确认通过**

```bash
python -m pytest tests/test_memory_manager.py::TestConsolidate tests/test_memory_manager.py::TestFormatContext -v
```

预期：全部 PASS

- [ ] **步骤 5：运行全部记忆测试**

```bash
python -m pytest tests/test_memory_manager.py -v
```

预期：全部 PASS

- [ ] **步骤 6：提交**

```bash
git add skills/obsidian/memory_manager.py tests/test_memory_manager.py
git commit -m "feat: add consolidate_and_flush, format_context, show_status"
```

---

## Task 5：从笔记字段提取词条 + CLI 入口

**文件：**
- 修改：`skills/obsidian/memory_manager.py`
- 修改：`tests/test_memory_manager.py`

- [ ] **步骤 1：写失败测试**

在 `tests/test_memory_manager.py` 末尾追加：

```python
from skills.obsidian.memory_manager import _extract_keywords

class TestExtractKeywords:
    def test_extracts_wikilinks(self):
        kws = _extract_keywords("参考 [[Titans论文]] 和 [[CMS设计]]")
        assert "Titans论文" in kws
        assert "CMS设计" in kws

    def test_extracts_hashtags(self):
        kws = _extract_keywords("这是 #AI #记忆系统 的内容")
        assert "AI" in kws
        assert "记忆系统" in kws

    def test_extracts_capitalized_english(self):
        kws = _extract_keywords("Titans and CMS are key concepts")
        assert "Titans" in kws
        assert "CMS" in kws

    def test_extracts_chinese_phrases(self):
        kws = _extract_keywords("活性记忆和遗忘机制是核心")
        assert "活性记忆" in kws or "遗忘机制" in kws

    def test_filters_stopwords(self):
        kws = _extract_keywords("的是了在和与或")
        assert kws == []

    def test_empty_text_returns_empty(self):
        assert _extract_keywords("") == []


class TestExtractAndUpsert:
    def test_concept_note_uses_title_as_word(self, vault):
        mm = MemoryManager(vault)
        mm.extract_and_upsert("concept", "Transformer", {"一句话定义": "一种注意力机制架构"}, "Concept - Transformer.md")
        assert "Transformer" in mm._long_term

    def test_literature_note_extracts_from_core_ideas(self, vault):
        mm = MemoryManager(vault)
        mm.extract_and_upsert("literature", "Titans论文", {"核心观点": "Self-Referential 模型可以自适应学习率"}, "Literature - Titans论文.md")
        words = list(mm._long_term.keys())
        # 应提取出 Self-Referential 或相关中文词
        assert len(words) > 0

    def test_topic_note_extracts_from_conclusions(self, vault):
        mm = MemoryManager(vault)
        mm.extract_and_upsert("topic", "记忆系统", {"当前结论": "CMS 多频率层优于传统双层记忆"}, "Topic - 记忆系统.md")
        words = list(mm._long_term.keys())
        assert len(words) > 0

    def test_skips_unsupported_note_types(self, vault):
        mm = MemoryManager(vault)
        mm.extract_and_upsert("moc", "AI MOC", {}, "MOC - AI.md")
        assert mm._long_term == {}
```

- [ ] **步骤 2：运行测试确认失败**

```bash
python -m pytest tests/test_memory_manager.py::TestExtractKeywords tests/test_memory_manager.py::TestExtractAndUpsert -v
```

预期：`ImportError` 或 `AttributeError: ... extract_and_upsert`

- [ ] **步骤 3：实现 extract_and_upsert 和 CLI**

在 `MemoryManager` 类中，`show_status` 方法后添加：

```python
    def extract_and_upsert(self, note_type: str, title: str, fields: dict, note_filename: str):
        """从笔记字段提取关键词并写入记忆库。写笔记后自动调用。"""
        if note_type == "concept":
            aliases = _extract_keywords(fields.get("一句话定义", ""))
            self.upsert(title, aliases=aliases, obsidian_link=note_filename)
        elif note_type == "literature":
            for kw in _extract_keywords(fields.get("核心观点", "")):
                self.upsert(kw, obsidian_link=note_filename)
        elif note_type == "topic":
            for kw in _extract_keywords(fields.get("当前结论", "")):
                self.upsert(kw, obsidian_link=note_filename)
        # moc / project / fleeting 暂不提取
```

在文件末尾追加 CLI 入口：

```python
# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description="活性记忆系统 CLI")
    parser.add_argument("--vault", default=os.environ.get("OBSIDIAN_VAULT_PATH", "~/obsidian"))
    parser.add_argument("--mode", required=True,
        choices=["query", "activate", "reinforce", "forget", "status", "flush", "decay"])
    parser.add_argument("--keywords", default="", help="逗号分隔的关键词（query 模式）")
    parser.add_argument("--word", default="", help="目标词（activate/reinforce/forget 模式）")
    args = parser.parse_args(argv)

    vault = Path(args.vault).expanduser()
    mm = MemoryManager(vault)

    if args.mode == "query":
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
        ctx = mm.format_context() if not keywords else ""
        if keywords:
            results = mm.query(keywords)
            for r in results:
                mm.activate(r["word"])
            ctx = mm.format_context()
        print(ctx or "[Memory] 无相关活性记忆")

    elif args.mode in ("activate", "reinforce"):
        if not args.word:
            print("[Error] --word 必填", file=sys.stderr)
            sys.exit(1)
        mm.activate(args.word)
        mm._save()
        print(f"[Memory] 已强化: {args.word}")

    elif args.mode == "forget":
        if not args.word:
            print("[Error] --word 必填", file=sys.stderr)
            sys.exit(1)
        if args.word in mm._long_term:
            del mm._long_term[args.word]
            mm._save()
            print(f"[Memory] 已淡忘: {args.word}")
        else:
            print(f"[Memory] 未找到: {args.word}")

    elif args.mode == "status":
        print(mm.show_status())

    elif args.mode == "flush":
        mm.consolidate_and_flush()
        print("[Memory] 会话巩固完成，已保存")

    elif args.mode == "decay":
        before = len(mm._long_term)
        mm.run_decay()
        mm.prune()
        mm._save()
        after = len(mm._long_term)
        print(f"[Memory] 衰减完成：{before} → {after} 条")


if __name__ == "__main__":
    main()
```

- [ ] **步骤 4：运行测试确认通过**

```bash
python -m pytest tests/test_memory_manager.py::TestExtractKeywords tests/test_memory_manager.py::TestExtractAndUpsert -v
```

预期：全部 PASS

- [ ] **步骤 5：运行全部记忆测试**

```bash
python -m pytest tests/test_memory_manager.py -v
```

预期：全部 PASS

- [ ] **步骤 6：提交**

```bash
git add skills/obsidian/memory_manager.py tests/test_memory_manager.py
git commit -m "feat: add extract_and_upsert and CLI entry for memory_manager"
```

---

## Task 6：集成 obsidian_writer.py

**文件：**
- 修改：`skills/obsidian/obsidian_writer.py`
- 修改：`tests/test_obsidian_writer.py`

- [ ] **步骤 1：写失败测试**

在 `tests/test_obsidian_writer.py` 末尾追加：

```python
class TestMemoryIntegration:
    """写笔记后，memory_manager 自动被调用。"""

    def test_write_concept_note_seeds_memory(self, tmp_path):
        """写入 concept 笔记后，_memory.jsonl 中应出现该词条。"""
        import json
        from skills.obsidian.memory_manager import MemoryManager, _MEMORY_FILE

        vault = tmp_path
        # 创建必要目录
        (vault / "03-Knowledge" / "Concepts").mkdir(parents=True)

        write_note(
            vault=vault,
            note_type="concept",
            title="Transformer",
            fields={"一句话定义": "注意力机制架构", "核心机制": "self-attention"},
            is_draft=False,
        )

        memory_file = vault / _MEMORY_FILE
        assert memory_file.exists(), "_memory.jsonl 应被创建"
        entries = [json.loads(l) for l in memory_file.read_text(encoding="utf-8").splitlines() if l]
        words = [e["word"] for e in entries]
        assert "Transformer" in words
```

- [ ] **步骤 2：运行测试确认失败**

```bash
python -m pytest tests/test_obsidian_writer.py::TestMemoryIntegration -v
```

预期：FAIL，`_memory.jsonl` 不存在

- [ ] **步骤 3：在 write_note 中集成记忆更新**

在 `obsidian_writer.py` 的 `write_note` 函数末尾，`return filepath` 前，添加：

```python
    # 记忆更新：提取关键词写入活性词库（跳过草稿和 fleeting/moc）
    if not is_draft and note_type not in ("moc", "fleeting"):
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent))
            from memory_manager import MemoryManager
            mm = MemoryManager(vault)
            mm.extract_and_upsert(note_type, title, fields, filepath.name)
            mm._save()
        except Exception:
            pass  # 记忆更新失败不阻断笔记写入
```

- [ ] **步骤 4：运行测试确认通过**

```bash
python -m pytest tests/test_obsidian_writer.py::TestMemoryIntegration -v
```

预期：PASS

- [ ] **步骤 5：运行全部测试确认无回归**

```bash
python -m pytest -v 2>&1 | tail -20
```

预期：所有原有测试仍通过

- [ ] **步骤 6：提交**

```bash
git add skills/obsidian/obsidian_writer.py tests/test_obsidian_writer.py
git commit -m "feat: integrate memory update into write_note"
```

---

## Task 7：扩展 SKILL.md（记忆注入 + memory 命令）

**文件：**
- 修改：`skills/obsidian/SKILL.md`

- [ ] **步骤 1：在 SKILL.md 顶部添加记忆上下文注入**

在 `SKILL.md` 第一行 `---` 之后、`description:` 字段之前，添加会话启动步骤（替换现有的 `---\ndescription:...` 开头部分）：

找到文件开头：
```
---
description: Write and organize notes in the Obsidian knowledge base. ...
---
```

替换为：
```
---
description: Write and organize notes in the Obsidian knowledge base. Handles quick fleeting notes, web/file capture, conversation logging, and archiving related notes. Triggered by /obsidian, or natural language like "记一下", "帮我整理这次对话", "抓取这个网页", "把这些笔记归档".
---

## 会话启动：注入活性记忆上下文

每次被调用时，**首先**运行以下命令获取当前活性记忆：

```bash
python ~/.claude/scripts/obsidian_writer.py --type memory-query \
  --fields '{"keywords": "<从用户消息提取的关键词，逗号分隔>"}'
```

或直接调用 memory_manager CLI：

```bash
python ~/.claude/skills/obsidian/memory_manager.py \
  --vault "${OBSIDIAN_VAULT_PATH:-~/obsidian}" \
  --mode query \
  --keywords "<关键词>"
```

将输出的 `<active_memory>...</active_memory>` 块视为"当前记忆激活状态"，在回答时优先引用这些词对应的知识。

**关键词提取规则：** 从用户消息中提取名词、英文大写词、`#标签`、`[[wikilink]]`，过滤停用词（的/是/了/in/the 等）。

---
```

- [ ] **步骤 2：在 SKILL.md 的 Step 1 检测表格中添加 memory 模式**

找到现有检测表格：
```
| User says | Mode |
|-----------|------|
| 记一下, 想到一个, 随手记, fleeting | `fleeting` |
```

在表格末尾追加一行：
```
| memory, 记忆状态, 活性词, 强化, 淡忘 | `memory` |
```

- [ ] **步骤 3：在 SKILL.md 末尾添加 memory 模式处理**

在 SKILL.md 最后一个 `---` 之前追加：

```markdown
---

## MODE: memory — 活性记忆管理

**Goal:** 查看、强化或淡忘活性词库中的词条。

### 子命令

| 用户说 | 操作 |
|--------|------|
| `/obsidian memory` 或 "记忆状态" | 显示 top-20 活性词 |
| `/obsidian memory reinforce <词>` 或 "强化 <词>" | 手动提升激活分数 |
| `/obsidian memory forget <词>` 或 "淡忘 <词>" | 从活性库中删除 |
| `/obsidian memory decay` 或 "运行衰减" | 立即执行衰减周期 |

### 执行命令

**显示状态：**
```bash
python ~/.claude/skills/obsidian/memory_manager.py \
  --vault "${OBSIDIAN_VAULT_PATH:-~/obsidian}" \
  --mode status
```

**强化词条：**
```bash
python ~/.claude/skills/obsidian/memory_manager.py \
  --vault "${OBSIDIAN_VAULT_PATH:-~/obsidian}" \
  --mode reinforce \
  --word "<词>"
```

**淡忘词条：**
```bash
python ~/.claude/skills/obsidian/memory_manager.py \
  --vault "${OBSIDIAN_VAULT_PATH:-~/obsidian}" \
  --mode forget \
  --word "<词>"
```

**运行衰减：**
```bash
python ~/.claude/skills/obsidian/memory_manager.py \
  --vault "${OBSIDIAN_VAULT_PATH:-~/obsidian}" \
  --mode decay
```

输出结果直接展示给用户，无需额外格式化。
```

- [ ] **步骤 4：在 install.py 中注册 memory_manager.py**

检查 `install.py` 中是否有注册 scripts 的逻辑，若有，确保 `memory_manager.py` 也被复制到 `~/.claude/skills/obsidian/`：

```bash
grep -n "obsidian_writer\|scripts\|copy" install.py
```

若 install.py 复制 skills 目录，memory_manager.py 自动包含在内（已在 `skills/obsidian/` 下），无需额外修改。

- [ ] **步骤 5：手动验证（无自动测试）**

SKILL.md 是 LLM prompt，无法自动化测试。手动验证：

```bash
# 确认 memory_manager CLI 可运行
python skills/obsidian/memory_manager.py --vault ~/obsidian --mode status

# 确认写笔记后记忆更新
python skills/obsidian/obsidian_writer.py \
  --type concept --title "TestConcept" \
  --fields '{"一句话定义": "测试概念", "核心机制": "测试"}' \
  --dry-run
# dry-run 模式不写文件，正常运行后检查 _memory.jsonl
```

- [ ] **步骤 6：运行全量测试**

```bash
python -m pytest -v 2>&1 | tail -20
```

预期：全部 PASS

- [ ] **步骤 7：提交**

```bash
git add skills/obsidian/SKILL.md
git commit -m "feat: extend SKILL.md with memory injection and memory commands"
```

---

## 自检结果

**Spec 覆盖核对：**
- [x] §3 双层架构 → Task 1（数据模型）+ Task 4（短期层）
- [x] §4 _memory.jsonl 数据模型 → Task 1
- [x] §5 激活公式 + 衰减场景 → Task 2
- [x] §5 会话巩固（睡眠效应） → Task 4
- [x] §5 容量上限 500 → Task 2（prune 支持 max_items 参数）
- [x] §6 上下文注入 + 关键词提取 → Task 5（extract_keywords）+ Task 7（SKILL.md）
- [x] §7 来源 A Obsidian 写入 → Task 6（obsidian_writer 集成）
- [x] §7 来源 B 对话激活 → Task 3（activate）
- [x] §9 新增命令 → Task 5（CLI）+ Task 7（SKILL.md）
- [x] §12 验收标准 5 条 → 分布在 Task 3、4、5、6 的测试中

**无占位符，无类型不一致，接口名称全程一致。**
