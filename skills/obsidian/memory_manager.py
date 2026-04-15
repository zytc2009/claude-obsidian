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
    wikilinks = [m.split('|')[0].strip() for m in re.findall(r'\[\[([^\]]+)\]\]', text)]
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
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
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
            entry["last_activated"] = datetime.now().isoformat(timespec="seconds")
            if aliases:
                existing = set(entry.get("aliases", []))
                entry["aliases"] = list(existing | set(aliases))
            if obsidian_link:
                links = list(entry.get("obsidian_links", []))
                if obsidian_link not in links:
                    links.append(obsidian_link)
                entry["obsidian_links"] = links
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
